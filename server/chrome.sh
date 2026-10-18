#!/bin/sh
# Download Chrome from Google into the browser volume, or bring it up to
# date, and point /browser/current at it. Runs as root at every start.
#
# Chrome is never part of the image. apt fetches it from Google's own
# package list and checks it against Google's signing key, whose fingerprint
# the image was built against (see the Dockerfile). The package is unpacked
# into the volume rather than installed, so a new image does not mean a new
# download, and only the newest version and the one before it are kept.
#
# Without a connection the Chrome already in the volume is used. With none
# there, it says so and the container stops.
set -eu

BROWSER=/browser
APT_LOG=/tmp/chrome-apt.log
APT="-o Dir::Etc::sourcelist=sources.list.d/paperpull-chrome.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 -o APT::Sandbox::User=root"

say() { echo "[chrome] $*"; }

installed() {
  [ -x "$BROWSER/$1/opt/google/chrome/chrome" ]
}

# CAP_SYS_ADMIN in this container's bounding set, bit 21 of CapBnd, which it
# holds only when the person added it with cap_add.
given_sys_admin() {
  bnd=$(awk '/^CapBnd:/ {print $2}' /proc/self/status 2>/dev/null)
  case "$bnd" in ""|*[!0-9a-fA-F]*) return 1 ;; esac
  [ $(( (0x$bnd >> 21) & 1 )) -eq 1 ]
}

# The seccomp-bpf filter, the other half of Chrome's sandbox, asked of the
# server's own host check (paperpull_core.host_sandbox), so there is one
# probe. Anything but a yes counts as no.
kernel_has_seccomp() {
  python -c "import sys; from paperpull_core.host_sandbox import check; sys.exit(0 if check().seccomp_bpf == 'yes' else 1)" 2>/dev/null
}

SETUID_SANDBOX=0
if given_sys_admin; then
  if kernel_has_seccomp; then
    SETUID_SANDBOX=1
    say "The container has SYS_ADMIN, so Chrome's setuid sandbox helper is set up, for a kernel without user namespaces."
    if awk '$2 == "/browser" {print $4}' /proc/mounts | grep -qw nosuid; then
      say "But /browser is mounted nosuid, so the kernel ignores the helper's setuid bit, and where"
      say "the kernel has no user namespaces Chrome will refuse to start. Mount it without nosuid."
    fi
  else
    say "The container has SYS_ADMIN, but this kernel has no seccomp, so Chrome's setuid sandbox helper"
    say "is not set up, since Chrome would have only half its sandbox. See \"On Synology\" in SERVER.md."
  fi
fi

have=""
if [ -L "$BROWSER/current" ]; then
  have=$(basename "$(readlink "$BROWSER/current")")
fi

wanted=""
# shellcheck disable=SC2086
if apt-get update $APT >"$APT_LOG" 2>&1; then
  wanted=$(apt-cache policy google-chrome-stable | awk '/Candidate:/ {print $2}')
  [ "$wanted" = "(none)" ] && wanted=""
fi

# Everyone may read Chrome and run it, the user pp among them, whatever the
# package's own folder modes were. Done at every start, so a Chrome unpacked
# by an earlier version of this script is put right too.
readable() {
  chmod -R a+rX "$BROWSER/$1"
  sandbox_helpers "$1"
}

# chrome-sandbox is Chrome's setuid helper, and the package ships it setuid
# root. Where the kernel gives user namespaces, Chrome's sandbox needs no
# helper that runs as root, so by default no copy in the volume keeps the
# bit. Some NAS kernels, Synology's among them, have no user namespaces at
# all, and there Chrome builds the same sandbox through this helper, which
# needs CAP_SYS_ADMIN to make the sandbox's namespaces. So in a container
# given SYS_ADMIN with cap_add, on a kernel with seccomp, see "On Synology"
# in SERVER.md, the helper of the Chrome in use ($1) is made setuid root,
# and every other copy
# loses the bit, so taking SYS_ADMIN away again, or an older Chrome kept
# beside the new one, leaves none behind. The sandbox is on either way, this
# is never --no-sandbox. Runs after the recursive chmod above, the owner is
# set before the mode since a change of owner drops the bit, and a link is
# never followed.
sandbox_helpers() {
  for entry in "$BROWSER"/*; do
    [ -L "$entry" ] && continue
    helper="$entry/opt/google/chrome/chrome-sandbox"
    { [ -f "$helper" ] && [ ! -L "$helper" ]; } || continue
    if [ "$SETUID_SANDBOX" = 1 ] && [ "$entry" = "$BROWSER/$1" ]; then
      chown 0:0 "$helper" && chmod 4755 "$helper" || say "Chrome's setuid sandbox helper could not be set up."
    else
      chmod 0755 "$helper" 2>/dev/null || true
    fi
  done
}

if [ -z "$wanted" ]; then
  if [ -n "$have" ] && installed "$have"; then
    readable "$have"
    say "Google could not be reached to look for a newer Chrome, so Chrome $have is used."
    exit 0
  fi
  say "Chrome is not downloaded yet, and Google could not be reached."
  say "The container needs to reach dl.google.com once, when it first starts."
  sed 's/^/[chrome]   /' "$APT_LOG" | tail -5
  exit 1
fi

if [ "$wanted" = "$have" ] && installed "$have"; then
  readable "$have"
  say "Chrome $have is up to date."
  exit 0
fi

say "Downloading Chrome $wanted from Google."
work=$(mktemp -d)
# shellcheck disable=SC2086
if ! (cd "$work" && apt-get download $APT "google-chrome-stable=$wanted") >>"$APT_LOG" 2>&1; then
  rm -rf "$work"
  if [ -n "$have" ] && installed "$have"; then
    readable "$have"
    say "The download did not finish, so Chrome $have is used for now."
    exit 0
  fi
  say "The download did not finish."
  sed 's/^/[chrome]   /' "$APT_LOG" | tail -5
  exit 1
fi

rm -rf "$BROWSER/$wanted.part" "$BROWSER/$wanted"
dpkg-deb -x "$work"/google-chrome-stable_*.deb "$BROWSER/$wanted.part"
rm -rf "$work"
readable "$wanted.part"
mv "$BROWSER/$wanted.part" "$BROWSER/$wanted"
ln -sfn "$wanted" "$BROWSER/current.new"
mv -T "$BROWSER/current.new" "$BROWSER/current"

# Older versions go. The links are skipped, since a link to a folder given
# to rm with a slash after it would empty the folder it points at.
for entry in "$BROWSER"/*; do
  [ -L "$entry" ] && continue
  [ -d "$entry" ] || continue
  name=$(basename "$entry")
  [ "$name" = "$wanted" ] || [ "$name" = "$have" ] || rm -rf "$entry"
done
say "Chrome $wanted is ready."
