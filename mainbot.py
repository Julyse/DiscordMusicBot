import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import os
import asyncio
import hashlib
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Vérification si TOKEN est bien chargé
if TOKEN is None:
    raise ValueError("Le TOKEN est None. Assurez-vous que la variable DISCORD_TOKEN est définie dans le fichier .env")

# Configurez les intentions
intents = discord.Intents.default()
intents.message_content = True  # Active les intentions de contenu des messages
intents.guilds = True  # Active les intentions des guilds
intents.voice_states = True  # Active les intentions pour les états vocaux (nécessaire pour les bots de musique)

# Créez le bot en passant les intentions
bot = commands.Bot(command_prefix='!', intents=intents)

# Dossier de cache
CACHE_DIR = Path('cache')
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Les options pour yt_dlp
def get_ytdl_format_options(filename=None):
    return {
        'format': 'bestaudio/best',
        'outtmpl': str(CACHE_DIR / '%(extractor)s-%(id)s-%(title)s.%(ext)s') if not filename else filename,
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'ffmpeg_location': os.getenv('FFMPEG_PATH')
    }

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(get_ytdl_format_options())

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, loop=None, stream=False):
        ytdl = youtube_dl.YoutubeDL(get_ytdl_format_options())
        
        # Générer un nom de fichier basé sur l'URL (pour éviter les répétitions de téléchargement)
        filename = CACHE_DIR / hashlib.md5(url.encode()).hexdigest()

        # Si le fichier existe déjà dans le cache, l'utiliser directement
        if filename.with_suffix('.mp3').exists():
            return cls(discord.FFmpegPCMAudio(str(filename.with_suffix('.mp3')), **ffmpeg_options), data={'title': url})

        # Sinon, télécharger le fichier et le stocker dans le cache
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        final_filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(final_filename, **ffmpeg_options), data=data)

queue = []
play_lock = asyncio.Lock()
next_track = None

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} est prêt.')

async def prefetch_next_track():
    global next_track
    if queue:
        url = queue[0]  # Prend l'URL de la prochaine vidéo dans la file d'attente
        next_track = await YTDLSource.from_url(url, loop=bot.loop)
    else:
        next_track = None

async def play_next(ctx):
    async with play_lock:
        if queue and next_track:
            player = next_track  # Utilise la piste préchargée
            queue.pop(0)  # Retire l'URL de la file d'attente

            if ctx.voice_client and ctx.voice_client.is_connected():
                ctx.voice_client.play(player, after=lambda e: bot.loop.create_task(play_next(ctx)))
                await ctx.send(f'En train de jouer: {player.title}')
                await prefetch_next_track()  # Précharge la piste suivante
            else:
                await ctx.send("Le bot n'est plus connecté à un canal vocal.")
        else:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()

@bot.command(name='join', help='Commande pour faire joindre le bot à un canal vocal')
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send(f"{ctx.message.author.name} n'est pas connecté à un canal vocal")
        return
    else:
        channel = ctx.message.author.voice.channel
    await channel.connect()

@bot.command(name='leave', help='Commande pour faire quitter le bot d\'un canal vocal')
async def leave(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
    else:
        await ctx.send("Le bot n'est pas connecté à un canal vocal.")

@bot.command(name='play', help='Commande pour lire de la musique à partir d\'une URL')
async def play(ctx, url):
    if not ctx.message.author.voice:
        await ctx.send(f"{ctx.message.author.name} n'est pas connecté à un canal vocal")
        return
    else:
        channel = ctx.message.author.voice.channel

    if not ctx.voice_client:
        await channel.connect()
    else:
        if ctx.voice_client.channel != channel:
            await ctx.voice_client.move_to(channel)

    queue.append(url)
    await ctx.send(f'Ajouté à la file d\'attente: {url}')

    if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
        await play_next(ctx)
    elif len(queue) == 1:  # Si c'est la première piste, préchargez la suivante après avoir commencé à jouer
        await prefetch_next_track()

@bot.command(name='pause', help='Commande pour mettre en pause la lecture de la musique')
async def pause(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client.is_playing():
        voice_client.pause()
    else:
        await ctx.send("Aucune musique n'est en cours de lecture.")

@bot.command(name='resume', help='Commande pour reprendre la lecture de la musique mise en pause')
async def resume(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client is paused():
        voice_client.resume()
    else:
        await ctx.send("La musique n'est pas en pause.")

@bot.command(name='skip', help='Commande pour passer à la musique suivante dans la file d\'attente')
async def skip(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await play_next(ctx)
    else:
        await ctx.send("Aucune musique n'est en cours de lecture.")

@bot.command(name='stop', help='Commande pour arrêter la lecture de la musique et vider la file d\'attente')
async def stop(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        queue.clear()
    else:
        await ctx.send("Aucune musique n'est en cours de lecture.")

# Démarrer le bot
bot.run(TOKEN)
