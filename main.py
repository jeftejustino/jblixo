import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import re
import time
import os
from collections import deque

# ─────────────────────────────────────────────
#  CONFIGURAÇÃO — edite aqui
# ─────────────────────────────────────────────
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN não configurado")
PREFIX = "lx"                       # Prefixo dos comandos
# ─────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# Estado por servidor
queues:        dict[int, deque]           = {}
now_playing:   dict[int, dict]            = {}
loop_mode:     dict[int, str]             = {}
player_msg:    dict[int, discord.Message] = {}
start_time:    dict[int, float]           = {}
pause_time:    dict[int, float]           = {}
paused_at:     dict[int, float]           = {}

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

YTDL_PLAYLIST_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "noplaylist": False,
    "yes_playlist": True,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


# ─── Helpers ───────────────────────────────────

def get_queue(guild_id: int) -> deque:
    if guild_id not in queues:
        queues[guild_id] = deque()
    return queues[guild_id]


def format_duration(seconds) -> str:
    if not seconds:
        return "?:??"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def progress_bar(elapsed: int, total: int, length: int = 20) -> str:
    if not total:
        return "─" * length
    ratio = min(elapsed / total, 1.0)
    filled = int(ratio * length)
    bar = "▬" * filled + "🔵" + "─" * (length - filled)
    return bar


def get_elapsed(guild_id: int) -> int:
    if guild_id not in start_time:
        return 0
    paused = pause_time.get(guild_id, 0)
    if guild_id in paused_at:
        return int(paused_at[guild_id] - start_time[guild_id] - paused)
    return int(time.time() - start_time[guild_id] - paused)


def build_player_embed(guild_id: int) -> discord.Embed:
    track  = now_playing.get(guild_id)
    queue  = get_queue(guild_id)
    lmode  = loop_mode.get(guild_id, "off")
    voice  = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    paused = voice and voice.is_paused()

    if not track:
        return discord.Embed(title="Nada tocando", color=0x2b2d31)

    elapsed = get_elapsed(guild_id)
    total   = track.get("duration") or 0
    bar     = progress_bar(elapsed, total)

    loop_icons = {"off": "➡️", "track": "🔂", "queue": "🔁"}
    status     = "⏸️ Pausado" if paused else "▶️ Tocando agora"

    embed = discord.Embed(
        title=status,
        color=0xf0a500 if paused else 0x1DB954,
    )
    embed.description = (
        f"### [{track['title']}]({track['webpage_url']})\n"
        f"\n"
        f"`{format_duration(elapsed)}` {bar} `{format_duration(total)}`\n"
        f"\n"
        f"🔀 Loop: **{lmode}** {loop_icons[lmode]}　｜　🎵 Na fila: **{len(queue)}**"
    )

    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])

    embed.set_footer(text=f"Use {PREFIX}queue para ver a fila completa")
    return embed


def build_player_view(guild_id: int) -> discord.ui.View:
    voice  = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    paused = voice and voice.is_paused()
    lmode  = loop_mode.get(guild_id, "off")

    view = discord.ui.View(timeout=None)

    view.add_item(discord.ui.Button(
        emoji="▶️" if paused else "⏸️",
        style=discord.ButtonStyle.secondary,
        custom_id=f"player_pause_{guild_id}",
    ))
    view.add_item(discord.ui.Button(
        emoji="⏭️",
        style=discord.ButtonStyle.secondary,
        custom_id=f"player_skip_{guild_id}",
    ))
    loop_labels = {"off": "🔁 Loop: off", "track": "🔂 Loop: track", "queue": "🔁 Loop: fila"}
    view.add_item(discord.ui.Button(
        label=loop_labels[lmode],
        style=discord.ButtonStyle.primary if lmode != "off" else discord.ButtonStyle.secondary,
        custom_id=f"player_loop_{guild_id}",
    ))
    view.add_item(discord.ui.Button(
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        custom_id=f"player_stop_{guild_id}",
    ))
    return view


async def send_or_update_player(guild_id: int, channel: discord.TextChannel = None):
    embed = build_player_embed(guild_id)
    view  = build_player_view(guild_id)
    msg   = player_msg.get(guild_id)

    if msg:
        try:
            await msg.edit(embed=embed, view=view)
            return
        except (discord.NotFound, discord.HTTPException):
            player_msg.pop(guild_id, None)

    if channel:
        new_msg = await channel.send(embed=embed, view=view)
        player_msg[guild_id] = new_msg


async def fetch_info(query: str, loop: asyncio.AbstractEventLoop) -> list[dict]:
    is_url      = bool(re.match(r"https?://", query))
    is_playlist = is_url and "list=" in query

    if is_playlist and "watch?" in query:
        list_id = re.search(r"list=([^&]+)", query).group(1)
        query   = f"https://www.youtube.com/playlist?list={list_id}"

    tracks = []

    if is_playlist:
        with yt_dlp.YoutubeDL(YTDL_PLAYLIST_OPTS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))

        for entry in (info.get("entries") or []):
            if not entry:
                continue
            vid_id      = entry.get("id") or entry.get("url", "")
            webpage_url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"
            thumb = entry.get("thumbnail")
            if not thumb:
                thumbs = entry.get("thumbnails")
                if thumbs and isinstance(thumbs, list):
                    thumb = thumbs[-1].get("url")
            tracks.append({
                "url":           None,
                "webpage_url":   webpage_url,
                "title":         entry.get("title", "Desconhecido"),
                "duration":      entry.get("duration", 0),
                "thumbnail":     thumb,
                "id":            vid_id,
                "_needs_resolve": True,
            })
    else:
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))

        if "entries" in info:
            info = info["entries"][0]

        tracks.append({
            "url":           info["url"],
            "webpage_url":   info.get("webpage_url", query),
            "title":         info.get("title", "Desconhecido"),
            "duration":      info.get("duration", 0),
            "thumbnail":     info.get("thumbnail"),
            "id":            info.get("id"),
            "_needs_resolve": False,
        })

    return tracks


async def resolve_track(track: dict, loop: asyncio.AbstractEventLoop) -> dict:
    if not track.get("_needs_resolve"):
        return track

    with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
        info = await loop.run_in_executor(
            None, lambda: ydl.extract_info(track["webpage_url"], download=False)
        )

    track["url"]            = info["url"]
    track["title"]          = info.get("title", track["title"])
    track["duration"]       = info.get("duration", track["duration"])
    track["thumbnail"]      = info.get("thumbnail", track.get("thumbnail"))
    track["_needs_resolve"] = False
    return track


# ─── Reprodução ────────────────────────────────

async def play_next(guild: discord.Guild, voice_client: discord.VoiceClient, text_channel: discord.TextChannel):
    guild_id = guild.id
    queue    = get_queue(guild_id)

    if loop_mode.get(guild_id) == "track" and guild_id in now_playing:
        track = now_playing[guild_id]
    elif loop_mode.get(guild_id) == "queue" and guild_id in now_playing:
        queue.append(now_playing[guild_id])
        if not queue:
            now_playing.pop(guild_id, None)
            return
        track = queue.popleft()
    else:
        if not queue:
            now_playing.pop(guild_id, None)
            player_msg.pop(guild_id, None)
            await text_channel.send(embed=discord.Embed(
                title="✅ Fila finalizada",
                description=f"Adicione mais músicas com `{PREFIX}play`",
                color=0x2b2d31,
            ))
            return
        track = queue.popleft()

    try:
        track = await resolve_track(track, bot.loop)
    except Exception as e:
        await text_channel.send(f"❌ Erro ao carregar **{track['title']}**: `{e}`")
        await play_next(guild, voice_client, text_channel)
        return

    now_playing[guild_id] = track
    start_time[guild_id]  = time.time()
    pause_time[guild_id]  = 0
    paused_at.pop(guild_id, None)

    source = discord.FFmpegPCMAudio(track["url"], **FFMPEG_OPTS)
    source = discord.PCMVolumeTransformer(source, volume=0.7)

    def after(error):
        if error:
            print(f"[Erro FFmpeg] {error}")
        asyncio.run_coroutine_threadsafe(
            play_next(guild, voice_client, text_channel), bot.loop
        )

    voice_client.play(source, after=after)
    await send_or_update_player(guild_id, text_channel)


# ─── Task: atualiza progresso a cada 15s ───────

@tasks.loop(seconds=15)
async def update_players():
    for guild_id, msg in list(player_msg.items()):
        voice = discord.utils.get(bot.voice_clients, guild__id=guild_id)
        if not voice or (not voice.is_playing() and not voice.is_paused()):
            continue
        try:
            await msg.edit(embed=build_player_embed(guild_id), view=build_player_view(guild_id))
        except Exception:
            pass


# ─── Botões do player ──────────────────────────

@bot.event
async def on_interaction(interaction: discord.Interaction):
    cid = interaction.data.get("custom_id", "")
    if not cid.startswith("player_"):
        return

    parts    = cid.split("_")
    action   = parts[1]
    guild_id = int(parts[2])
    voice    = discord.utils.get(bot.voice_clients, guild__id=guild_id)

    await interaction.response.defer()

    if action == "pause":
        if voice and voice.is_playing():
            voice.pause()
            paused_at[guild_id] = time.time()
        elif voice and voice.is_paused():
            if guild_id in paused_at:
                pause_time[guild_id] = pause_time.get(guild_id, 0) + (time.time() - paused_at[guild_id])
                paused_at.pop(guild_id)
            voice.resume()

    elif action == "skip":
        if loop_mode.get(guild_id) == "track":
            loop_mode[guild_id] = "off"
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
        return

    elif action == "loop":
        modes = ["off", "track", "queue"]
        cur   = loop_mode.get(guild_id, "off")
        loop_mode[guild_id] = modes[(modes.index(cur) + 1) % len(modes)]

    elif action == "stop":
        get_queue(guild_id).clear()
        now_playing.pop(guild_id, None)
        loop_mode[guild_id] = "off"
        start_time.pop(guild_id, None)
        pause_time.pop(guild_id, None)
        paused_at.pop(guild_id, None)
        if voice:
            voice.stop()
            await voice.disconnect()
        msg = player_msg.pop(guild_id, None)
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        return

    await send_or_update_player(guild_id)


# ─── Comandos ──────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot online como {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name=f"{PREFIX}help"
    ))
    update_players.start()


@bot.command(name="play", aliases=["p"])
async def play(ctx: commands.Context, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Você precisa estar em um canal de voz!", delete_after=8)

    voice = ctx.guild.voice_client
    if voice is None:
        voice = await ctx.author.voice.channel.connect()
    elif ctx.author.voice.channel != voice.channel:
        await voice.move_to(ctx.author.voice.channel)

    async with ctx.typing():
        try:
            tracks = await fetch_info(query, bot.loop)
        except Exception as e:
            return await ctx.send(f"❌ Erro ao buscar: `{e}`", delete_after=10)

    try:
        await ctx.message.delete()
    except Exception:
        pass

    queue = get_queue(ctx.guild.id)

    if len(tracks) == 1:
        queue.append(tracks[0])
        if not voice.is_playing() and not voice.is_paused():
            await play_next(ctx.guild, voice, ctx.channel)
        else:
            thumb = tracks[0].get("thumbnail") or ""
            e = discord.Embed(
                title="➕ Adicionado à fila",
                description=f"**{tracks[0]['title']}** — posição #{len(queue)}",
                color=0x1DB954,
            )
            if thumb:
                e.set_thumbnail(url=thumb)
            await ctx.send(embed=e, delete_after=10)
    else:
        for t in tracks:
            queue.append(t)
        await ctx.send(embed=discord.Embed(
            title="📋 Playlist adicionada",
            description=f"**{len(tracks)} músicas** adicionadas à fila.",
            color=0x1DB954,
        ), delete_after=8)
        if not voice.is_playing() and not voice.is_paused():
            await play_next(ctx.guild, voice, ctx.channel)


@bot.command(name="skip", aliases=["s"])
async def skip(ctx: commands.Context):
    voice = ctx.guild.voice_client
    if voice and (voice.is_playing() or voice.is_paused()):
        if loop_mode.get(ctx.guild.id) == "track":
            loop_mode[ctx.guild.id] = "off"
        voice.stop()
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="pause")
async def pause(ctx: commands.Context):
    voice = ctx.guild.voice_client
    if voice and voice.is_playing():
        voice.pause()
        paused_at[ctx.guild.id] = time.time()
        await send_or_update_player(ctx.guild.id)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="resume", aliases=["r"])
async def resume(ctx: commands.Context):
    voice = ctx.guild.voice_client
    gid   = ctx.guild.id
    if voice and voice.is_paused():
        if gid in paused_at:
            pause_time[gid] = pause_time.get(gid, 0) + (time.time() - paused_at[gid])
            paused_at.pop(gid)
        voice.resume()
        await send_or_update_player(gid)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="stop")
async def stop(ctx: commands.Context):
    gid = ctx.guild.id
    get_queue(gid).clear()
    now_playing.pop(gid, None)
    loop_mode[gid] = "off"
    start_time.pop(gid, None)
    pause_time.pop(gid, None)
    paused_at.pop(gid, None)
    voice = ctx.guild.voice_client
    if voice:
        voice.stop()
        await voice.disconnect()
    msg = player_msg.pop(gid, None)
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="queue", aliases=["q", "fila"])
async def show_queue(ctx: commands.Context):
    gid     = ctx.guild.id
    queue   = get_queue(gid)
    current = now_playing.get(gid)

    if not current and not queue:
        return await ctx.send("🎵 Fila vazia", delete_after=8)

    desc = ""
    if current:
        elapsed = get_elapsed(gid)
        total   = current.get("duration") or 0
        desc   += f"**▶️ Tocando agora:**\n`{current['title']}`\n`{format_duration(elapsed)} / {format_duration(total)}`\n\n"

    if queue:
        desc += "**Próximas:**\n"
        for i, t in enumerate(list(queue)[:15], 1):
            desc += f"`{i}.` {t['title']} `{format_duration(t.get('duration', 0))}`\n"
        if len(queue) > 15:
            desc += f"\n*...e mais {len(queue) - 15} músicas*"

    lmode      = loop_mode.get(gid, "off")
    loop_label = {"track": "🔂 Track", "queue": "🔁 Fila", "off": "❌ Off"}[lmode]
    await ctx.send(embed=discord.Embed(
        title=f"🎵 Fila — {len(queue)} músicas  |  Loop: {loop_label}",
        description=desc,
        color=0x1DB954,
    ), delete_after=30)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="nowplaying", aliases=["np"])
async def nowplaying(ctx: commands.Context):
    await send_or_update_player(ctx.guild.id, ctx.channel)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="loop")
async def loop_cmd(ctx: commands.Context, mode: str = None):
    gid   = ctx.guild.id
    modes = ["off", "track", "queue"]
    cur   = loop_mode.get(gid, "off")

    if mode is None:
        mode = modes[(modes.index(cur) + 1) % len(modes)]
    else:
        mode = mode.lower()

    if mode not in modes:
        return await ctx.send("❌ Use: `off`, `track` ou `queue`", delete_after=6)

    loop_mode[gid] = mode
    await send_or_update_player(gid)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="volume", aliases=["vol"])
async def volume(ctx: commands.Context, vol: int):
    voice = ctx.guild.voice_client
    if not voice or not (voice.is_playing() or voice.is_paused()):
        return await ctx.send("❌ Nada tocando agora", delete_after=6)
    if not 0 <= vol <= 100:
        return await ctx.send("❌ Volume deve ser entre 0 e 100", delete_after=6)
    voice.source.volume = vol / 100
    await ctx.send(f"🔊 Volume: **{vol}%**", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="remove")
async def remove(ctx: commands.Context, index: int):
    queue = get_queue(ctx.guild.id)
    if index < 1 or index > len(queue):
        return await ctx.send("❌ Índice inválido", delete_after=6)
    q_list  = list(queue)
    removed = q_list.pop(index - 1)
    queues[ctx.guild.id] = deque(q_list)
    await ctx.send(f"🗑️ Removido: **{removed['title']}**", delete_after=6)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="clear", aliases=["limpar"])
async def clear_queue(ctx: commands.Context):
    get_queue(ctx.guild.id).clear()
    await ctx.send("🗑️ Fila limpa", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command(name="help", aliases=["ajuda", "h"])
async def help_cmd(ctx: commands.Context):
    p = PREFIX
    embed = discord.Embed(title="🎵 Comandos do Bot", color=0x1DB954)
    embed.add_field(name="Reprodução", value=(
        f"`{p}play <nome ou URL>` — Toca música ou playlist\n"
        f"`{p}pause` / `{p}resume` — Pausa / Retoma\n"
        f"`{p}skip` — Pula a música atual\n"
        f"`{p}stop` — Para e desconecta\n"
        f"`{p}nowplaying` — Mostra o player\n"
        f"`{p}volume <0-100>` — Ajusta o volume"
    ), inline=False)
    embed.add_field(name="Fila", value=(
        f"`{p}queue` — Mostra a fila\n"
        f"`{p}remove <nº>` — Remove uma música\n"
        f"`{p}clear` — Limpa a fila"
    ), inline=False)
    embed.add_field(name="Loop", value=(
        f"`{p}loop [off|track|queue]` — Alterna o modo de loop\n"
        "Ou clique no botão 🔁 diretamente no player"
    ), inline=False)
    embed.set_footer(text="Dica: os botões no player também controlam a reprodução!")
    await ctx.send(embed=embed, delete_after=30)
    try:
        await ctx.message.delete()
    except Exception:
        pass


bot.run(TOKEN)