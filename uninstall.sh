#!/bin/bash
# Quadify uninstall script — reverses install.sh.
# Volumio runs <plugindir>/uninstall.sh during UI uninstall.
# Idempotent: every step guards for absence and never exits non-zero on
# already-removed items. install.sh is the source of truth for paths/markers.

# Never abort the whole uninstall on a single failed step.
set +e

log() { echo "[Quadify Uninstall] $*"; }

# Match install.sh's boot dir detection (/boot, or /boot/firmware if present)
BOOTDIR="/boot"
[ -d /boot/firmware ] && BOOTDIR="/boot/firmware"

# ---------------------------------------------------------------------------
# 1) systemd units Quadify created
#    disable --now (ignore if absent), then remove the unit file.
# ---------------------------------------------------------------------------
QUADIFY_UNITS="
quadify.service
quadify-splash.service
quadify-icon-fetch.service
quadify-buttonsleds.service
ir_listener.service
early_led8.service
cava.service
quadify-lirc-post.service
quadify-leds-off.service
volumio-clean-poweroff.service
"

log "Stopping, disabling and removing Quadify systemd units…"
for unit in $QUADIFY_UNITS; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  if [ -f "/etc/systemd/system/$unit" ]; then
    rm -f "/etc/systemd/system/$unit"
    log "Removed /etc/systemd/system/$unit"
  fi
done

log "Reloading systemd daemon…"
systemctl daemon-reload >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 2) Helper scripts in /usr/local/bin
# ---------------------------------------------------------------------------
log "Removing helper scripts from /usr/local/bin…"
for f in \
  /usr/local/bin/quadify-blank-irexec.sh \
  /usr/local/bin/quadify-leds-off.py \
  /usr/local/bin/clean-poweroff.sh; do
  if [ -e "$f" ]; then
    rm -f "$f"
    log "Removed $f"
  fi
done

# ---------------------------------------------------------------------------
# 3) /etc/quadify (whole directory)
# ---------------------------------------------------------------------------
if [ -d /etc/quadify ]; then
  rm -rf /etc/quadify
  log "Removed /etc/quadify"
fi

# ---------------------------------------------------------------------------
# 4) sudoers drop-in
# ---------------------------------------------------------------------------
if [ -f /etc/sudoers.d/quadify-lirc ]; then
  rm -f /etc/sudoers.d/quadify-lirc
  log "Removed /etc/sudoers.d/quadify-lirc"
fi

# ---------------------------------------------------------------------------
# 5) Samba: remove ONLY the [Quadify] stanza, leave the rest of smb.conf.
#    Drop from the "[Quadify]" header up to the next "[section]" header
#    (or EOF, since install.sh appends it last). Do NOT touch the SMB password.
# ---------------------------------------------------------------------------
SMB_CONF="/etc/samba/smb.conf"
if [ -f "$SMB_CONF" ] && grep -q '^\[Quadify\]' "$SMB_CONF"; then
  log "Removing [Quadify] share from $SMB_CONF…"
  tmp="$(mktemp)"
  awk '
    /^\[Quadify\]/ { skip=1; next }
    skip && /^\[/  { skip=0 }
    !skip          { print }
  ' "$SMB_CONF" > "$tmp" && cat "$tmp" > "$SMB_CONF"
  rm -f "$tmp"
  log "Reloading smbd/nmbd…"
  systemctl reload smbd nmbd >/dev/null 2>&1 || true
else
  log "No [Quadify] share present in $SMB_CONF; skipping."
fi

# ---------------------------------------------------------------------------
# 6) Boot overlays in userconfig.txt — remove ONLY Quadify's overlays.
#    LEAVE dtparam=i2c_arm=on and dtparam=spi=on (shared with other DACs).
# ---------------------------------------------------------------------------
UCFG="$BOOTDIR/userconfig.txt"
if [ -f "$UCFG" ]; then
  log "Removing Quadify boot overlays from $UCFG…"
  sed -i \
    -e '/^dtoverlay=gpio-ir/d' \
    -e '/^dtoverlay=gpio-shutdown/d' \
    -e '/^dtoverlay=gpio-poweroff/d' \
    "$UCFG"
  log "Left dtparam=i2c_arm=on / dtparam=spi=on intact (shared)."
else
  log "No $UCFG present; skipping overlay cleanup."
fi

# ---------------------------------------------------------------------------
# 7) MPD FIFO block — remove the marker-delimited block (inclusive).
# ---------------------------------------------------------------------------
MPD_TMPL="/volumio/app/plugins/music_service/mpd/mpd.conf.tmpl"
if [ -f "$MPD_TMPL" ] && grep -q '# --- QUADIFY_CAVA_FIFO_START ---' "$MPD_TMPL"; then
  log "Removing QUADIFY_CAVA_FIFO block from $MPD_TMPL…"
  sed -i '/# --- QUADIFY_CAVA_FIFO_START ---/,/# --- QUADIFY_CAVA_FIFO_END ---/d' "$MPD_TMPL"
else
  log "No QUADIFY_CAVA_FIFO block in $MPD_TMPL; skipping."
fi

# ---------------------------------------------------------------------------
# 8) /home/volumio/lircd.conf symlink
# ---------------------------------------------------------------------------
if [ -L /home/volumio/lircd.conf ] || [ -e /home/volumio/lircd.conf ]; then
  rm -f /home/volumio/lircd.conf
  log "Removed /home/volumio/lircd.conf symlink"
fi

# ---------------------------------------------------------------------------
# 9) Restore stock LIRC files Quadify overwrote (from .quadify.bak backups).
#    For each: if the backup exists, restore it and remove the backup.
# ---------------------------------------------------------------------------
restore_from_bak() {
  # $1 = live file, $2 = backup file
  if [ -f "$2" ]; then
    cp -a "$2" "$1"
    rm -f "$2"
    log "Restored $1 from $(basename "$2")"
  fi
}

log "Restoring stock LIRC files from backups (if present)…"
restore_from_bak /etc/lirc/lirc_options.conf /etc/lirc/lirc_options.conf.quadify.bak
restore_from_bak /etc/lirc/lircd.conf        /etc/lirc/lircd.conf.quadify.bak
restore_from_bak /etc/lirc/irexec.lircrc     /etc/lirc/irexec.lircrc.quadify.bak

# Re-enable any lircd.conf.d profiles Quadify disabled (*.disabled -> *.conf)
if [ -d /etc/lirc/lircd.conf.d ]; then
  for f in /etc/lirc/lircd.conf.d/*.disabled; do
    [ -e "$f" ] || continue
    mv -f "$f" "${f%.disabled}"
    log "Re-enabled $(basename "${f%.disabled}")"
  done
fi

log "Uninstall complete."
exit 0
