# 🎵 Discord Music Bot — Guia de Instalação

## Pré-requisitos

- Python 3.10 ou superior → https://python.org/downloads
- FFmpeg → https://ffmpeg.org/download.html (veja instruções abaixo)

---

## 1. Instalar o FFmpeg

### Windows
1. Baixe o build em: https://www.gyan.dev/ffmpeg/builds/ → pegue o `ffmpeg-release-essentials.zip`
2. Extraia e copie a pasta para `C:\ffmpeg`
3. Adicione `C:\ffmpeg\bin` ao PATH do sistema:
   - Pesquise "Variáveis de Ambiente" no menu Iniciar
   - Em "Variáveis do sistema" → `Path` → Editar → Novo → cole `C:\ffmpeg\bin`
4. Teste: abra o CMD e rode `ffmpeg -version`

### Linux (Ubuntu/Debian)
```bash
sudo apt update && sudo apt install ffmpeg -y
```

---

## 2. Criar o Bot no Discord

1. Acesse https://discord.com/developers/applications
2. Clique em **New Application** → dê um nome
3. Vá em **Bot** → clique em **Add Bot**
4. Em **Privileged Gateway Intents**, ative:
   - ✅ MESSAGE CONTENT INTENT
   - ✅ SERVER MEMBERS INTENT (opcional)
5. Clique em **Reset Token** e copie o token
6. Cole o token no arquivo `bot.py` onde diz `SEU_TOKEN_AQUI`

### Convidar o bot para o servidor
1. Vá em **OAuth2** → **URL Generator**
2. Marque os escopos: `bot`
3. Em permissões, marque:
   - `Send Messages`, `Embed Links`, `Connect`, `Speak`
4. Copie a URL gerada e abra no navegador para adicionar ao servidor

---

## 3. Instalar as dependências Python

Abra o terminal na pasta do bot e rode:

```bash
pip install -r requirements.txt
```

---

## 4. Rodar o Bot

```bash
python bot.py
```

O terminal mostrará: `✅ Bot online como NomeDoBot`

Para rodar em segundo plano no Windows, crie um arquivo `iniciar.bat`:
```bat
@echo off
pythonw bot.py
```

---

## Comandos Disponíveis

| Comando | Descrição |
|---|---|
| `!play <nome ou URL>` | Toca uma música (nome, link do vídeo ou **link de playlist**) |
| `!pause` | Pausa a reprodução |
| `!resume` | Retoma a reprodução |
| `!skip` | Pula para a próxima música |
| `!stop` | Para tudo e desconecta o bot |
| `!queue` | Mostra a fila atual |
| `!nowplaying` | Mostra a música tocando agora |
| `!remove <nº>` | Remove uma música da fila |
| `!clear` | Limpa a fila sem parar a música |
| `!loop [off\|track\|queue]` | Muda o modo de loop |
| `!volume <0-100>` | Ajusta o volume |
| `!help` | Lista todos os comandos |

### Exemplos de uso com playlist
```
!play https://www.youtube.com/playlist?list=PLxxxxxxxx
!play lo-fi hip hop mix
!play https://www.youtube.com/watch?v=xxxxxxxx
```

---

## Solução de Problemas

**"ffmpeg not found"** → Verifique se o FFmpeg está no PATH (passo 1)

**Bot não entra no canal de voz** → Verifique as permissões do bot no servidor

**Música não toca / erro de yt-dlp** → Atualize o yt-dlp:
```bash
pip install -U yt-dlp
```

**Token inválido** → Gere um novo token no portal de desenvolvedores
