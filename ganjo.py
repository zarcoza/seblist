import asyncio
import re
import datetime
import sys
import os
import threading
import logging

from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask

# === KONFIGURASI TELEGRAM ===
api_id = 27165484
api_hash = 'b5f28de58166f16d6fedc4e0fd29a859'
client = TelegramClient('user_session', api_id, api_hash)

# === SETUP LOGGER ===
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s'
    )

# === SCHEDULER ===
scheduler = AsyncIOScheduler()

# === DATA GLOBAL ===
blacklisted_groups = set()
job_data = {}
delay_setting = {}
MASA_AKTIF = datetime(2030, 12, 31)
delay_per_group_setting = {}  # Menyimpan delay per user (detik)
pesan_simpan = {}  # key: user_id, value: pesan terbaru
preset_pesan = {}  # key: user_id, value: {nama_preset: isi_pesan}
usage_stats = {}  # key: user_id, value: jumlah pesan yang berhasil dikirim
start_time = datetime.now()
TOTAL_SENT_MESSAGES = 0
JOBS = {}
ALLOWED_USERS = {7605681637, 1538087933, 1735348722}  # Ganti dengan ID admin awal
ALLOWED_USERS_FILE = 'allowed_users.txt'

# === FUNGSI LOAD & SAVE ALLOWED USERS ===
def load_allowed_users():
    try:
        with open(ALLOWED_USERS_FILE, 'r') as file:
            return [int(line.strip()) for line in file if line.strip()]
    except FileNotFoundError:
        return []


def save_allowed_users():
    with open(ALLOWED_USERS_FILE, 'w') as f:
        f.write("\n".join(map(str, load_allowed_users())))


async def is_allowed(event):
    try:
        sender = await event.get_sender()
        allowed_users = load_allowed_users()
        return sender.id in allowed_users
    except Exception as e:
        print(f"[ERROR] Saat memeriksa is_allowed: {e}")
        return False

# === MAPPING HARI ===
HARI_MAPPING = {
    'senin': 'monday', 'selasa': 'tuesday', 'rabu': 'wednesday',
    'kamis': 'thursday', 'jumat': 'friday', 'sabtu': 'saturday',
    'minggu': 'sunday'
}

# === UPDATE USAGE STATISTICS ===
def update_usage(user_id, count):
    global TOTAL_SENT_MESSAGES
    usage_stats[user_id] = usage_stats.get(user_id, 0) + count
    TOTAL_SENT_MESSAGES += count

ALLOWED_USERS = load_allowed_users()

# === FUNCTION UNTUK MELAKUKAN FORWARDING PESAN ===
async def forward_job(
    user_id, mode, source, message_id_or_text,
    jumlah_grup, durasi_jam: float, jumlah_pesan,
    delay_per_group: int = 0
):
    start = datetime.now()
    end = start + timedelta(hours=durasi_jam)
    jeda_batch = delay_setting.get(user_id, 5)
    now = datetime.now()
    next_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    harian_counter = 0
    total_counter = 0

    info_msg = f"[{now:%H:%M:%S}] 💖 Mulai meneruskan pesan selama {durasi_jam:.2f} jam~"
    print(info_msg)
    logging.info(info_msg)

    try:
        await client.send_message(
            user_id,
            f"⏱💗 Sedang meneruskan pesan...\nDurasi: {durasi_jam:.2f} jam\nTarget harian: {jumlah_pesan} pesan."
        )
    except Exception as e:
        logging.error(f"💔 Error kirim notifikasi ke {user_id}: {e}")

    while datetime.now() < end:
        if datetime.now() >= next_reset:
            harian_counter = 0
            next_reset += timedelta(days=1)
            reset_msg = (
                f"[{datetime.now():%H:%M:%S}] 💖 Reset harian: lanjut besok yaa, sayang!"
            )
            print(reset_msg)
            logging.info(reset_msg)

        counter = 0
        async for dialog in client.iter_dialogs():
            if datetime.now() >= end or harian_counter >= jumlah_pesan:
                break
            if not dialog.is_group or dialog.name in blacklisted_groups:
                continue
            try:
                if mode == 'forward':
                    msg = await client.get_messages(source, ids=int(message_id_or_text))
                    if msg:
                        await client.forward_messages(
                            dialog.id, msg.id, from_peer=source
                        )
                else:
                    await client.send_message(
                        dialog.id, message_id_or_text, link_preview=True
                    )

                counter += 1
                harian_counter += 1
                total_counter += 1
                update_usage(user_id, 1)

                log_msg = (
                    f"[{datetime.now():%H:%M:%S}] 💗✅ Sukses dikirim ke grup: {dialog.name}"
                )
                print(log_msg)
                logging.info(log_msg)

                if delay_per_group > 0:
                    await asyncio.sleep(delay_per_group)

                if counter >= jumlah_grup or harian_counter >= jumlah_pesan:
                    break

            except Exception as e:
                error_msg = (
                    f"[{datetime.now():%H:%M:%S}] 💔❌ Gagal dikirim ke grup {dialog.name}: {e}"
                )
                print(error_msg)
                logging.error(error_msg)
                continue

        if harian_counter >= jumlah_pesan:
            notif = (
                f"🎯 Target harian {jumlah_pesan} pesan tercapai!\n"
                "Bot lanjut lagi besok bub, tetap semangat sebarnya ya!"
            )
            info_notif = f"[{datetime.now():%H:%M:%S}] 💖 {notif}"
            print(info_notif)
            logging.info(info_notif)
            try:
                await client.send_message(user_id, notif)
            except Exception as e:
                logging.error(f"💔 Error kirim notifikasi ke {user_id}: {e}")

            sleep_seconds = (next_reset - datetime.now()).total_seconds()
            await asyncio.sleep(sleep_seconds)
        else:
            batch_msg = (
                f"[{datetime.now():%H:%M:%S}] 💞 Batch {counter} grup selesai. Istirahat {jeda_batch} detik dulu ya..."
            )
            print(batch_msg)
            logging.info(batch_msg)
            await asyncio.sleep(jeda_batch)

    selesai = (
        f"✅ Forward selesai!\nTotal terkirim ke {total_counter} grup selama {durasi_jam:.2f} jam."
    )
    selesai_msg = f"[{datetime.now():%H:%M:%S}] 💖 {selesai}"
    print(selesai_msg)
    logging.info(selesai_msg)
    try:
        await client.send_message(user_id, selesai)
    except Exception as e:
        logging.error(f"💔 Error kirim pesan selesai ke {user_id}: {e}")

# === PERINTAH BOT ===

@client.on(events.NewMessage(pattern='/scheduleforward'))
async def schedule_cmd(event):
    args = event.message.raw_text.split(maxsplit=2)
    if len(args) < 3:
        return await event.respond(
            "❌ Format salah:\n"
            "/scheduleforward mode pesan/sumber jumlah_grup durasi jeda jumlah_pesan hari,jam jam:menit"
        )
    try:
        mode = args[1]
        sisa = args[2].rsplit(' ', 6)
        if len(sisa) != 7:
            return await event.respond(
                "❌ Format tidak sesuai. Pastikan argumen lengkap!"
            )
        isi_pesan, jumlah, durasi, jeda, jumlah_pesan, hari_str, waktu = sisa
        jumlah = int(jumlah)
        durasi = int(durasi)
        jeda = int(jeda)
        jumlah_pesan = int(jumlah_pesan)
        jam, menit = map(int, waktu.split(':'))
        hari_list = [HARI_MAPPING.get(h.lower()) for h in hari_str.split(',')]
        if None in hari_list:
            return await event.respond(
                "❌ Terdapat nama hari yang tidak valid. Gunakan: senin,selasa,...,minggu."
            )

        for hari_eng in hari_list:
            job_id = f"{event.sender_id}{hari_eng}{int(datetime.now().timestamp())}"
            job_data[job_id] = {
                'user': event.sender_id,
                'mode': mode,
                'source': '',
                'message': isi_pesan,
                'jumlah': jumlah,
                'durasi': durasi,
                'jeda': jeda,
                'jumlah_pesan': jumlah_pesan
            }
            delay_setting[event.sender_id] = jeda
            scheduler.add_job(
                forward_job,
                trigger=CronTrigger(day_of_week=hari_eng, hour=jam, minute=menit),
                args=[event.sender_id, mode, '', isi_pesan, jumlah, durasi, jumlah_pesan],
                id=job_id
            )

        daftar_hari = ', '.join([h.title() for h in hari_str.split(',')])
        await event.respond(
            f"💗 Jadwal forward berhasil ditambahkan untuk hari {daftar_hari} pukul {waktu}!"
        )
    except Exception as e:
        err_msg = f"💔 Error: {e}"
        logging.error(err_msg)
        await event.respond(err_msg)

@client.on(events.NewMessage(pattern='/forward'))
async def forward_sekarang(event):
    args = event.message.raw_text.split(maxsplit=7)
    if len(args) < 7:
        return await event.respond(
            "❌ Format salah:\n"
            "/forward mode sumber/id/isipesan jumlah_grup jeda durasi jumlah_pesan"
        )
    try:
        mode = args[1]
        if mode == 'forward':
            source = args[2]
            jumlah = int(args[3])
            message_id = int(args[4])
            jeda_batch = int(args[5])
            durasi = int(args[6])
            jumlah_pesan = int(args[7]) if len(args) >= 8 else 300
            delay_setting[event.sender_id] = jeda_batch
            await forward_job(
                event.sender_id, mode, source, message_id, jumlah, durasi, jumlah_pesan
            )
        elif mode == 'text':
            text = args[2]
            jumlah = int(args[3])
            jeda_batch = int(args[4])
            durasi = int(args[5])
            jumlah_pesan = int(args[6]) if len(args) >= 7 else 300
            delay_setting[event.sender_id] = jeda_batch
            pesan_simpan[event.sender_id] = text
            await forward_job(
                event.sender_id, mode, '', text, jumlah, durasi, jumlah_pesan
            )
        else:
            await event.respond("❌ Mode harus 'forward' atau 'text'")
    except Exception as e:
        err_msg = f"💔 Error: {e}"
        logging.error(err_msg)
        await event.respond(err_msg)

@client.on(events.NewMessage(pattern='/setdelay'))
async def set_delay(event):
    try:
        delay = int(event.message.raw_text.split()[1])
        delay_setting[event.sender_id] = delay
        await event.respond(f"💗 Jeda antar batch diset ke {delay} detik!")
    except Exception as e:
        logging.error(f"💔 Error pada /setdelay: {e}")
        await event.respond("❌ Gunakan: /setdelay <detik>")

@client.on(events.NewMessage(pattern='/review'))
async def review_jobs(event):
    teks = "💗== Jadwal Aktif ==\n"
    if not job_data:
        teks += "Tidak ada jadwal."
    else:
        for job_id, info in job_data.items():
            teks += (
                f"- ID: {job_id}\n"
                f"  Mode: {info['mode']}\n"
                f"  Grup: {info['jumlah']}\n"
                f"  Durasi: {info['durasi']} jam\n"
            )
    await event.respond(teks)

@client.on(events.NewMessage(pattern='/deletejob'))
async def delete_job(event):
    try:
        job_id = event.message.raw_text.split()[1]
        scheduler.remove_job(job_id)
        job_data.pop(job_id, None)
        await event.respond("💗 Jadwal berhasil dihapus!")
    except Exception as e:
        logging.error(f"💔 Error pada /deletejob: {e}")
        await event.respond("❌ Gagal menghapus. Pastikan ID yang dimasukkan benar.")

@client.on(events.NewMessage(pattern='/stopforward'))
async def stop_forward(event):
    user_id = event.sender_id
    removed = []
    for job in scheduler.get_jobs():
        if str(user_id) in job.id:
            try:
                scheduler.remove_job(job.id)
                job_data.pop(job.id, None)
                removed.append(job.id)
            except Exception as e:
                logging.error(f"💔 Error menghapus job {job.id}: {e}")
    if removed:
        await event.respond(f"💗 Semua job forward untuk Anda telah dihapus: {', '.join(removed)}")
    else:
        await event.respond("❌ Tidak ditemukan job forward untuk Anda.")

@client.on(events.NewMessage(pattern='/blacklist_add'))
async def add_blacklist(event):
    try:
        nama = " ".join(event.message.raw_text.split()[1:])
        blacklisted_groups.add(nama)
        await event.respond(f"💗 '{nama}' berhasil masuk ke blacklist!")
    except Exception as e:
        logging.error(f"💔 Error pada /blacklist_add: {e}")
        await event.respond("❌ Format salah. Gunakan: /blacklist_add <nama>")

@client.on(events.NewMessage(pattern='/blacklist_remove'))
async def remove_blacklist(event):
    try:
        nama = " ".join(event.message.raw_text.split()[1:])
        blacklisted_groups.discard(nama)
        await event.respond(f"💗 '{nama}' telah dihapus dari blacklist!")
    except Exception as e:
        logging.error(f"💔 Error pada /blacklist_remove: {e}")
        await event.respond("❌ Format salah. Gunakan: /blacklist_remove <nama>")

@client.on(events.NewMessage(pattern='/list_blacklist'))
async def list_blacklist(event):
    if not blacklisted_groups:
        await event.respond("💗 Blacklist kosong!")
    else:
        teks = "💗== Grup dalam blacklist ==\n" + "\n".join(blacklisted_groups)
        await event.respond(teks)

@client.on(events.NewMessage(pattern='/status'))
async def cek_status(event):
    now = datetime.now()
    sisa = (MASA_AKTIF - now).days
    tanggal_akhir = MASA_AKTIF.strftime('%d %B %Y')
    await event.respond(
        f"💖 Masa aktif tersisa: {sisa} hari\n"
        f"💖 Userbot aktif sampai: {tanggal_akhir}"
    )

@client.on(events.NewMessage(pattern='/review_pesan'))
async def review_pesan(event):
    pesan = pesan_simpan.get(event.sender_id)
    if not pesan:
        await event.respond("💗 Belum ada pesan yang disimpan.")
    else:
        await event.respond(f"💗== Isi Pesan Saat Ini ==\n{pesan}")

@client.on(events.NewMessage(pattern='/ubah_pesan'))
async def ubah_pesan(event):
    try:
        teks = event.message.raw_text.split(" ", maxsplit=1)[1]
        pesan_simpan[event.sender_id] = teks
        await event.respond("💗 Isi pesan berhasil diubah!")
    except Exception as e:
        logging.error(f"💔 Error pada /ubah_pesan: {e}")
        await event.respond("❌ Format salah. Gunakan:\n/ubah_pesan <teks>")

@client.on(events.NewMessage(pattern='/simpan_preset'))
async def simpan_preset(event):
    try:
        user_id = event.sender_id
        parts = event.message.raw_text.split(" ", maxsplit=2)
        if len(parts) < 3:
            return await event.respond("❌ Format salah. Gunakan:\n/simpan_preset <nama> <pesan>")
        _, nama, pesan = parts
        preset_pesan.setdefault(user_id, {})[nama] = pesan
        await event.respond(f"💗 Preset '{nama}' berhasil disimpan!")
    except Exception as e:
        logging.error(f"💔 Error pada /simpan_preset: {e}")
        await event.respond("❌ Format salah. Gunakan:\n/simpan_preset <nama> <pesan>")

@client.on(events.NewMessage(pattern='/pakai_preset'))
async def pakai_preset(event):
    try:
        user_id = event.sender_id
        nama = event.message.raw_text.split(" ", maxsplit=1)[1]
        pesan = preset_pesan.get(user_id, {}).get(nama)
        if not pesan:
            return await event.respond(f"❌ Tidak ada preset dengan nama '{nama}'!")
        pesan_simpan[user_id] = pesan
        await event.respond(f"💗 Preset '{nama}' dipilih:\n\n{pesan}")
    except Exception as e:
        logging.error(f"💔 Error pada /pakai_preset: {e}")
        await event.respond("❌ Format salah. Gunakan:\n/pakai_preset <nama>")

@client.on(events.NewMessage(pattern='/list_preset'))
async def list_preset(event):
    user_id = event.sender_id
    daftar = preset_pesan.get(user_id, {})
    if not daftar:
        return await event.respond("💗 Belum ada preset.")
    teks = "💗== Daftar Preset ==\n" + "\n".join(f"- {nama}" for nama in daftar)
    await event.respond(teks)

@client.on(events.NewMessage(pattern=r'^/setdelaygroup (\d+)$'))
async def set_delay_group(event):
    user_id = event.sender_id
    delay = int(event.pattern_match.group(1))
    delay_per_group_setting[user_id] = delay
    await event.reply(f"✨💗 Delay antar grup udah diset ke {delay} detik, sayang!")

@client.on(events.NewMessage(pattern=r'^/cekdelaygroup$'))
async def cek_delay_group(event):
    user_id = event.sender_id
    delay = delay_per_group_setting.get(user_id, 0)
    await event.reply((
        f"⏱💗 Delay antar grup kamu saat ini: {delay} detik.\n"
        "Makin rapih makin mantep kirimannya!"
    ))

@client.on(events.NewMessage(pattern=r'^/resetdelaygroup$'))
async def reset_delay_group(event):
    user_id = event.sender_id
    delay_per_group_setting.pop(user_id, None)
    await event.reply((
        "♻💗 Delay antar grup udah di-reset ke 0 detik, manis!\n"
        "Siap ngebut kirim pesan ke semua grup!"
    ))

@client.on(events.NewMessage(pattern='/edit_preset'))
async def edit_preset(event):
    try:
        user_id = event.sender_id
        parts = event.message.raw_text.split(" ", maxsplit=2)

        if len(parts) < 3:
            return await event.respond("❌ Format salah, bestie! Coba gini:\n/edit_preset <nama> <pesan>")

        _, nama, pesan_baru = parts

        if nama not in preset_pesan.get(user_id, {}):
            return await event.respond(f"❌ Nggak nemu preset dengan nama '{nama}' nih!")

        preset_pesan[user_id][nama] = pesan_baru
        await event.respond(f"✨ Preset '{nama}' berhasil di-update, ciyee!")

    except Exception as e:
        await event.respond(f"Upss! Ada error nih, sayang: {e} 💖")

@client.on(events.NewMessage(pattern='/hapus_preset'))
async def hapus_preset(event):
    if not await is_allowed(event): return
    try:
        nama = event.message.raw_text.split(' ',1)[1]
        del preset_pesan[event.sender_id][nama]
        await event.respond(f"💗 '{nama}' dihapus")
    except Exception:
        await event.respond("❌ /hapus_preset <nama>")

@client.on(events.NewMessage(pattern='/ping'))
async def ping(event):
    await event.respond("💖 Bot aktif dan siap melayani!")

@client.on(events.NewMessage(pattern='/restart'))
async def restart(event):
    await event.respond("💗 Bot akan restart...")
    logging.info("Restarting bot upon command...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

@client.on(events.NewMessage(pattern='/log'))
async def log_handler(event):
    try:
        with open('bot.log','r',encoding='utf-8') as log_file:
            logs = log_file.read()
            if len(logs) > 4000:
                logs = logs[-4000:]
            await event.respond(f"📜💗 Log Terbaru!:\n{logs}")
    except FileNotFoundError:
        await event.respond("❌ Log tidak ditemukan bub :(")
    except Exception:
        await event.respond("❌ Yahh ada masalah dalam membaca log.")

PENGEMBANG_USERNAME = "@explicist"
@client.on(events.NewMessage(pattern=r'/feedback(?:\s+(.*))?'))
async def feedback_handler(event):
    msg = event.pattern_match.group(1)

    if not msg:
        return await event.reply(
            "💖 Kirim saran/kritik atau pesan lain kepada pengembangku: /feedback <pesan>"
        )

    logging.info(f"Feedback dari {event.sender_id}: {msg}")

    # Balasan ke pengirim
    await event.reply(
        "💌 Terima kasih atas feedback-nya!\n"
        "Masukanmu sangat berarti dan akan kami baca dengan penuh cinta!"
    )

    # Buat format feedback
    sender = await event.get_sender()
    name = sender.first_name if sender else "Tidak diketahui"
    username = f"@{sender.username}" if sender and sender.username else "Tidak ada"
    user_id = sender.id if sender else "Tidak diketahui"
    message = msg

    feedback_text = (
        "💌 Feedback Baru!\n\n"
        f"• Dari: {name}\n"
        f"• Username: {username}\n"
        f"• ID: {user_id}\n"
        f"• Pesan: {message}"
    )

        # Kirim feedback ke pengembang
    try:
        await client.send_message(PENGEMBANG_USERNAME, feedback_text)
    except Exception as e:
        await event.reply("Ups! Gagal mengirim feedback ke pengembang. Coba lagi nanti yaaw.")
        print(f"[Feedback Error] {e}")

@client.on(events.NewMessage(pattern=r'/reply (\d+)\s+([\s\S]+)', from_users=PENGEMBANG_USERNAME))
async def reply_to_user(event):
    match = event.pattern_match
    user_id = int(match.group(1))
    reply_message = match.group(2).strip()
    try:
        await client.send_message(user_id, f"💬 Pesan dari pengembang:\n\n{reply_message}")
        await event.reply("✅ Balasanmu sudah dikirim ke pengguna!")
    except Exception as e:
        await event.reply("❌ Gagal mengirim balasan ke pengguna. Mungkin user sudah block bot?")
        print(f"[Reply Error] {e}")

@client.on(events.NewMessage(pattern=r'^/help\b'))
async def help_cmd(event):
    # if not await is_allowed(event):
    #     return
    await event.respond("Tes /help bekerja!")
    teks = """
✨💖 PANDUAN USERBOT HEARTIE 💖✨
Hai, sayang! Aku Heartie, userbot-mu yang siap membantu menyebarkan pesan cinta ke semua grup-grup favoritmu. Berikut daftar perintah yang bisa kamu gunakan:
============================
/forward
Kirim pesan langsung ke grup.
— Mode forward (dari channel):
 /forward forward @namachannel jumlah_grup id_pesan jeda detik durasi jam jumlah_pesan_perhari
 Contoh: /forward forward @usnchannel 50 27 5 3 300
— Mode text (kirim teks langsung):
 /forward text "Halo semua!" jumlah_grup jeda detik durasi jam jumlah_pesan_perhari
 Contoh: /forward text "Halo semua!" 10 5 3 300
============================
2. /scheduleforward
 Jadwalkan pesan mingguan otomatis.
 — Format:
 /scheduleforward mode pesan/sumber jumlah_grup durasi jeda jumlah_pesan hari1,day2 jam:menit
 — Contoh:
 /scheduleforward forward @usnchannel 20 2 5 300 senin,jumat 08:00
 /scheduleforward text "Halo dari bot!" 30 3 5 300 selasa,rabu 10:00
============================
3. Manajemen Preset & Pesan
 — /review_pesan — Lihat pesan default
 — /ubah_pesan — Ubah pesan default
 — /simpan_preset — Simpan preset pesan
 — /pakai_preset — Pilih preset sebagai pesan default
 — /list_preset — Tampilkan daftar preset
 — /edit_preset — Edit preset pesan
 — /hapus_preset — Hapus preset
============================
4. Pengaturan Job Forward & Delay
 — /review — Tampilkan jadwal aktif
 — /deletejob — Hapus jadwal forward
 — /setdelay — Atur jeda antar batch kirim
 — /stopforward — Hentikan semua job forward aktif kamu
 — /setdelaygroup 5 — Set delay antar grup ke 5 detik (bisa diubah)
 — /cekdelaygroup — Cek delay antar grup kamu saat ini
 — /resetdelaygroup — Reset delay antar grup ke default
============================
5. Blacklist Grup
 — /blacklist_add — Tambahkan grup ke blacklist
 — /blacklist_remove — Hapus grup dari blacklist
 — /list_blacklist — Lihat daftar grup dalam blacklist
============================
6. User Allowed
 — /adduserbutton — Menambahkan daftar user yang diizinkan memakai userbot
 — /listuser — Menampilkan daftar user yang diizinkan memakai userbot
============================
7. Info & Lain-lain
 — /status — Cek masa aktif userbot
 — /ping — Periksa apakah bot aktif
 — /log — Tampilkan log aktivitas bot
 — /feedback — Kirim feedback ke pengembang
 — /stats — Lihat statistik penggunaan forward
 — /restart — Restart bot
============================
✨ Cara mendapatkan ID pesan channel:
Klik kanan bagian kosong (atau tap lama) pada pesan di channel → Salin link.
Misal, jika linknya  maka id pesan adalah 19.
Selamat mencoba dan semoga hari-harimu penuh cinta! 💗 Kalau masih ada yang bingung bisa chat pengembangku/kirimkan feedback ya!
"""
    await event.respond(teks)

@client.on(events.NewMessage(pattern='/info'))
async def info_handler(event):
    if not await is_allowed(event):
        return
    now = datetime.now()
    uptime = now - start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    aktif_sejak = start_time.strftime("%d %B %Y pukul %H:%M WIB")

    text = (
        "💖 Tentang Heartie Bot 💖\n\n"
        "Haiii! Aku Heartie, sahabatmu yang selalu setia meneruskan pesan penuh cinta ke grup-grup kesayanganmu~\n\n"
        "✨ Dibuat oleh: [@explicist](https://t.me/explicist)\n"
        "🛠 Versi: 1.2.0\n"
        "🧠 Ditenagai oleh: Python + Telethon\n"
        "🎯 Fungsi: Kirim & jadwalkan pesan otomatis ke banyak grup\n\n"
        f"⏳ Uptime: {hours} jam, {minutes} menit\n"
        f"📅 Aktif sejak: {aktif_sejak}\n\n"
        "Butuh bantuan? Yuk klik tombol di bawah ini~ 💗"
    )

    buttons = [
        [Button.inline("📖 Panduan /help", data=b"show_help")],
        [Button.inline("📊 Lihat Statistik", data=b"refresh_stats")],
        [Button.url("💬 Hubungi Pembuat", url="https://t.me/explicist")]
    ]

    await event.respond(text, buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery)
async def callback_handler(event):
    if not await is_allowed(event):
        return
    if event.data == b"refresh_stats":
        await stats_handler(event)
        await event.answer("Statistik diperbarui!")

    elif event.data == b"show_help":
        await help_cmd(event)
        await event.answer("Ini panduannya~")

    elif event.data == b"download_log":
        try:
            await client.send_file(event.chat_id, 'logs.txt', caption="📄 Ini dia log-nya yaa!")
            await event.answer("Log dikirim!")
        except FileNotFoundError:
            await event.answer("Log belum tersedia~", alert=True)

@client.on(events.NewMessage(pattern='/stats'))
async def stats_handler(event):
    if not await is_allowed(event):
        return
    try:
        global TOTAL_SENT_MESSAGES

        sender = await event.get_sender()
        name = sender.first_name or "Pengguna"
        username = f"@{sender.username}" if sender.username else "(tanpa username)"
        chat_id = event.chat_id

        try:
            with open('allowed_users.txt', 'r') as f:
                total_users = len(f.readlines())
        except FileNotFoundError:
            total_users = 1

        stats_text = (
            f"💖 Haii {name} ({username})!\n\n"
            "📊 Statistik Heartie Bot:\n"
            f"• Total job aktif: {len(JOBS)}\n"
            f"• Total pesan terkirim: {TOTAL_SENT_MESSAGES}\n"
            f"• Total pengguna terdaftar: {total_users}\n"
            f"• Waktu server sekarang: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        buttons = [
            [Button.inline("🔄 Refresh", data=b"refresh_stats")],
            [Button.inline("📥 Download Log", data=b"download_log")]
        ]

        await event.respond(stats_text, buttons=buttons, parse_mode='markdown')
        TOTAL_SENT_MESSAGES += 1
    except Exception as e:
        await event.respond(f"❌ Terjadi kesalahan: {e}")

@client.on(events.NewMessage(pattern=r'/adduserbutton'))
async def add_user_button(event):
    if not await is_allowed(event):
        return await event.reply("❌ Kamu nggak punya izin buat ini, ciyee.")

    async for user in client.iter_participants('me'):
        break

    keyboard = [
        [Button.inline("➕ Izinkan Saya Sendiri", data=f"add_{user.id}".encode())]
    ]

    await event.reply(
        "💖 Pilih siapa yang mau kamu izinkan jadi pengguna bot ini yaa:",
        buttons=keyboard
    )

@client.on(events.CallbackQuery(data=re.compile(rb'add_(\d+)')))
async def handler_add_button(event):
    if not await is_allowed(event):
        return await event.answer("Kamu nggak punya izin!", alert=True)

    add_id = int(event.data_match.group(1))

    if add_id in ALLOWED_USERS:
        return await event.answer("✨ User ini sudah diizinkan sebelumnya kok!", alert=True)

    ALLOWED_USERS.add(add_id)
    save_allowed_users()

    try:
        user = await client.get_entity(add_id)
        nama = user.first_name or "Tanpa Nama"
        username = f"@{user.username}" if user.username else "(tanpa username)"
    except Exception:
        nama = "Tidak diketahui"
        username = "(tanpa username)"

    await event.edit(
        f"✨ Yey! User ini sekarang sudah jadi bagian dari Heartie Club!\n\n"
        f"• Nama: {nama}\n"
        f"• Username: {username}\n"
        f"• ID: {add_id}"
    )

@client.on(events.NewMessage(pattern=r'/listuser'))
async def list_users(event):
    if not await is_allowed(event):
        return

    if not ALLOWED_USERS:
        return await event.reply("💖 Belum ada user yang diizinkan, sayang...")

    teks = "✨ Daftar pengguna yang diizinkan:\n\n"
    buttons = []

    for uid in sorted(ALLOWED_USERS):
        try:
            user = await client.get_entity(uid)
            nama = user.first_name or "Tanpa Nama"
            username = f"@{user.username}" if user.username else "(tanpa username)"
        except Exception:
            nama = "Tidak diketahui"
            username = "(tanpa username)"

        teks += f"• {nama} | {username} | {uid}\n"
        buttons.append(Button.inline(f"❌ Hapus {uid}", data=f"remove_{uid}".encode()))

    await event.reply(teks, buttons=buttons)

@client.on(events.CallbackQuery(data=re.compile(rb'remove_(\d+)')))
async def handler_remove_button(event):
    if not await is_allowed(event):
        return await event.answer("Kamu nggak punya izin!", alert=True)

    remove_id = int(event.data_match.group(1))

    if remove_id in ALLOWED_USERS:
        ALLOWED_USERS.remove(remove_id)
        save_allowed_users()
        try:
            user = await client.get_entity(remove_id)
            nama = user.first_name or "Tanpa Nama"
            username = f"@{user.username}" if user.username else "(tanpa username)"
        except Exception:
            nama = "Tidak diketahui"
            username = "(tanpa username)"

        await event.edit(
            f"❌ {remove_id} telah dihapus dari daftar user yang diizinkan.\n"
            f"• Nama: {nama}\n"
            f"• Username: {username}"
        )
    else:
        await event.answer("User sudah tidak ada di daftar!", alert=True)

# === PENGECEKAN LISENSI ===
async def cek_lisensi():
    if datetime.now() > MASA_AKTIF:
        logging.error("💔 Lisensi expired. Bot dihentikan.")
        sys.exit("💔 Lisensi expired.")

# === SETUP FLASK UNTUK KEEP ALIVE ===
app = Flask(__name__)

@app.route('/')
def home():
    return "💗 Heartie Bot is alive!"

@app.route('/ping')
def ping():
    return "✅ Xixi! Bot masih hidup."

def keep_alive():
    app.run(host="0.0.0.0", port=8000)

threading.Thread(target=keep_alive).start()

# === JALANKAN BOT ===
async def main():
    await client.start()
    scheduler.start()
    await cek_lisensi()
    me = await client.get_me()
    welcome_msg = f"💖 Bot aktif, kamu masuk sebagai {me.first_name}. Menunggu perintahmu, sayang!"
    print(welcome_msg)
    logging.info(welcome_msg)
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
