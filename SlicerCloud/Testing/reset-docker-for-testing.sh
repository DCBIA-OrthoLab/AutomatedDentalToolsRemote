#!/bin/sh
# reset-docker-for-testing.sh -- put this machine back to "never had Docker".
#
# TEMPORARY. This exists only to re-test the Slicer Cloud panel's first-run
# path (install Docker -> join the docker group -> enable the GPU -> start the
# server) without hunting for a fresh machine every time. DELETE THIS FILE once
# that path is done being tested. It is not shipped: SlicerCloud/CMakeLists.txt
# lists its files explicitly, so nothing here is packaged into the extension.
#
# THIS IS DESTRUCTIVE. It removes Docker, every image, every container, every
# volume, the server clone and the panel's saved settings. Run it on a test
# machine and nowhere else.
#
#   sh reset-docker-for-testing.sh --dry-run     # show what it would do
#   sh reset-docker-for-testing.sh               # ask, then do it
#   sh reset-docker-for-testing.sh --yes         # do it without asking
#
# Options:
#   --dry-run         print every step instead of running it
#   --yes             skip the confirmation prompt
#   --dir DIR         the server clone to delete (default: ~/slicerdocker)
#   --keep-nvidia     leave the NVIDIA Container Toolkit installed
#   --keep-settings   leave Slicer's saved settings alone
#
# What it deliberately does NOT touch: the NVIDIA GPU DRIVER. Removing it can
# need a reboot and a specific kernel package, and `install-docker.sh --nvidia`
# refuses to run without a working `nvidia-smi` -- so a machine with no driver
# cannot test the GPU path at all, which is the opposite of the point.

set -eu

DRY_RUN=0
ASSUME_YES=0
CLONE_DIR="$HOME/slicerdocker"
KEEP_NVIDIA=0
KEEP_SETTINGS=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --dir) CLONE_DIR="$2"; shift 2 ;;
        --keep-nvidia) KEEP_NVIDIA=1; shift ;;
        --keep-settings) KEEP_SETTINGS=1; shift ;;
        -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "reset-docker-for-testing: unknown option '$1'" >&2; exit 2 ;;
    esac
done

# Run as YOURSELF, not as root. The whole point is to remove *your* account
# from the docker group and clear *your* Slicer settings, and under `sudo sh`
# both $HOME and $USER are root's -- so it would clean the wrong account and
# leave the machine looking reset while the real user still had docker access.
if [ "$(id -u)" -eq 0 ]; then
    echo "reset-docker-for-testing: do not run this as root or with sudo." >&2
    echo "  Run it as your normal user; it calls sudo itself where it has to." >&2
    exit 1
fi

TARGET_USER="$(id -un)"

say() { printf '\n=== %s ===\n' "$1"; }

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  [dry-run] %s\n' "$*"
    else
        printf '  + %s\n' "$*"
        "$@"
    fi
}

# Purging a package that is not installed is an apt error, and with `set -e`
# that would abort the whole reset half way through. Only ever pass apt the
# packages that are actually there.
installed_of() {
    for pkg in "$@"; do
        if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null \
                | grep -q '^install ok installed'; then
            printf '%s ' "$pkg"
        fi
    done
}

# ---------------------------------------------------------------------------
# What is about to be destroyed
# ---------------------------------------------------------------------------

say "This machine"
printf '  host          %s\n' "$(hostname)"
printf '  user          %s\n' "$TARGET_USER"
printf '  clone         %s\n' "$CLONE_DIR"
if command -v docker >/dev/null 2>&1; then
    printf '  docker        %s\n' "$(docker --version 2>/dev/null || echo '?')"
    if docker info >/dev/null 2>&1; then
        echo "  --- images, containers and volumes that will be deleted ---"
        docker system df 2>/dev/null | sed 's/^/  /' || true
    fi
else
    echo "  docker        not installed"
fi

if [ "$ASSUME_YES" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    printf '\nThis DELETES Docker and everything it holds. Type "reset" to go ahead: '
    read -r answer
    if [ "$answer" != "reset" ]; then
        echo "Nothing was changed."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

say "Stopping docker"
# The socket first: leave it up and systemd restarts the daemon on the next
# docker command, so the purge below would be fighting a service coming back.
if command -v systemctl >/dev/null 2>&1; then
    run sudo systemctl stop docker.socket docker containerd || true
fi

say "Purging packages"
# Two package sets, because Docker ships its own and the distribution ships
# another -- a machine has one or the other, and the names have nothing in
# common. `installed_of` reduces each to what is really there.
DOCKER_OFFICIAL="docker-ce docker-ce-cli containerd.io docker-buildx-plugin
                 docker-compose-plugin docker-ce-rootless-extras docker-model-plugin"
DOCKER_DISTRO="docker.io docker-cli docker-compose docker-compose-v2 docker-buildx
               containerd runc"

# shellcheck disable=SC2086 -- deliberate word splitting of a package list
PACKAGES="$(installed_of $DOCKER_OFFICIAL $DOCKER_DISTRO)"
if [ -n "$PACKAGES" ]; then
    # shellcheck disable=SC2086
    run sudo apt-get purge -y $PACKAGES
    run sudo apt-get autoremove -y --purge
else
    echo "  (no docker packages installed)"
fi

if command -v snap >/dev/null 2>&1 && snap list docker >/dev/null 2>&1; then
    run sudo snap remove --purge docker
fi

say "Removing docker data and configuration"
# `purge` does not touch any of this, which is what makes a "clean" reinstall
# come back with all its old containers still there.
run sudo rm -rf /var/lib/docker /var/lib/containerd
run sudo rm -rf /etc/docker /etc/containerd
run rm -rf "$HOME/.docker"

say "Removing the apt repository and its key"
# Left in place, a reinstall silently reuses the existing source instead of
# exercising the part of install-docker.sh that adds it.
run sudo rm -f /etc/apt/sources.list.d/docker.list \
               /etc/apt/keyrings/docker.asc \
               /etc/apt/keyrings/docker.gpg \
               /usr/share/keyrings/docker-archive-keyring.gpg

say "Removing the docker group"
# Not cosmetic. install-docker.sh adds the user to this group and says to log
# out and back in; leaving the membership in place skips the exact step being
# tested -- and it is the step users get stuck on.
if getent group docker >/dev/null 2>&1; then
    run sudo gpasswd -d "$TARGET_USER" docker || true
    run sudo groupdel docker || true
else
    echo "  (no docker group)"
fi

# ---------------------------------------------------------------------------
# NVIDIA container toolkit -- never the driver
# ---------------------------------------------------------------------------

if [ "$KEEP_NVIDIA" -eq 0 ]; then
    say "Removing the NVIDIA Container Toolkit (NOT the driver)"
    NVIDIA_PKGS="nvidia-container-toolkit nvidia-container-toolkit-base
                 libnvidia-container-tools libnvidia-container1"

    # A guard on the LIST above, not on the system: every name here has to be a
    # container-runtime package. If someone ever adds a driver package to that
    # line, this refuses to run rather than leaving the machine unable to test
    # the GPU path at all -- and unable to display anything, possibly.
    for pkg in $NVIDIA_PKGS; do
        case "$pkg" in
            *driver*|*dkms*|*compute*|*utils*|*kernel*|*firmware*)
                echo "reset-docker-for-testing: refusing to purge '$pkg' -- that is a" >&2
                echo "  DRIVER package, and this script must never remove the driver." >&2
                exit 1 ;;
        esac
    done

    # shellcheck disable=SC2086
    NV_INSTALLED="$(installed_of $NVIDIA_PKGS)"
    if [ -n "$NV_INSTALLED" ]; then
        # shellcheck disable=SC2086
        run sudo apt-get purge -y $NV_INSTALLED
    else
        echo "  (toolkit not installed)"
    fi
    run sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list \
                   /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    # The CDI specs the toolkit generates. Left behind, docker keeps resolving
    # `nvidia.com/gpu` devices and the panel correctly reports a working GPU --
    # so the "docker cannot reach the card" case never gets tested.
    run sudo rm -rf /etc/cdi /var/run/cdi /etc/nvidia-container-runtime
fi

# ---------------------------------------------------------------------------
# The Slicer side
# ---------------------------------------------------------------------------

say "Removing the server clone"
if [ -e "$CLONE_DIR" ]; then
    run rm -rf "$CLONE_DIR"
else
    echo "  ($CLONE_DIR does not exist)"
fi

if [ "$KEEP_SETTINGS" -eq 0 ]; then
    say "Clearing the panel's saved settings"
    if pgrep -x Slicer >/dev/null 2>&1 || pgrep -f 'SlicerApp-real' >/dev/null 2>&1; then
        echo "  ! Slicer is RUNNING, and it rewrites this file from memory when it quits --" >&2
        echo "    so whatever is cleared here comes straight back. Close Slicer, then run" >&2
        echo "    this script again (the docker steps above are safe to repeat)." >&2
    fi
    # Every profile, not just the default one: a developer machine usually has
    # several (~/.slicer-configs/{dev,prod,...}), and cleaning only the default
    # leaves the panel remembering its install folder in the one being tested.
    found_ini=0
    for ini in "$HOME"/.config/slicer.org/Slicer.ini \
               "$HOME"/.slicer-configs/*/slicer.org/Slicer.ini; do
        [ -f "$ini" ] || continue
        grep -q '^\[SlicerCloud\]\|^\[ServerTools\]' "$ini" 2>/dev/null || continue
        found_ini=1
        printf '  %s\n' "$ini"
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "    [dry-run] would drop the [SlicerCloud] and [ServerTools] sections"
            continue
        fi
        cp "$ini" "$ini.before-reset"
        # Drop the two sections the extension owns, and only those. Deleting the
        # whole file would reset ALL of Slicer -- layout, modules, recent paths
        # -- which is a far bigger change than anyone asked this script for.
        awk '
            /^\[/ { skip = ($0 == "[SlicerCloud]" || $0 == "[ServerTools]") }
            !skip { print }
        ' "$ini.before-reset" > "$ini"
        echo "    dropped [SlicerCloud] and [ServerTools] (backup: $ini.before-reset)"
    done
    [ "$found_ini" -eq 1 ] || echo "  (nothing saved yet)"
fi

# ---------------------------------------------------------------------------
# Did it work?
# ---------------------------------------------------------------------------

say "Result"
if [ "$DRY_RUN" -eq 1 ]; then
    echo "  dry run -- nothing was changed."
    exit 0
fi

fail=0
check() {  # check <label> <ok|bad> [detail]
    if [ "$2" = "ok" ]; then
        printf '  ok   %s\n' "$1"
    else
        printf '  FAIL %s %s\n' "$1" "${3:-}"
        fail=1
    fi
}

command -v docker >/dev/null 2>&1 && check "docker removed" bad "(still in PATH)" \
                                  || check "docker removed" ok
command -v docker-compose >/dev/null 2>&1 && check "docker-compose removed" bad \
                                          || check "docker-compose removed" ok
[ -d /var/lib/docker ] && check "docker data removed" bad "(/var/lib/docker still there)" \
                       || check "docker data removed" ok
id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx docker \
    && check "out of the docker group" bad "(log out and back in)" \
    || check "out of the docker group" ok
[ -e "$CLONE_DIR" ] && check "clone removed" bad || check "clone removed" ok

if [ "$KEEP_NVIDIA" -eq 0 ]; then
    command -v nvidia-ctk >/dev/null 2>&1 && check "container toolkit removed" bad \
                                          || check "container toolkit removed" ok
fi

# The one thing that must have SURVIVED. Checked last and loudly: without it,
# `install-docker.sh --nvidia` refuses to run and the GPU path cannot be tested.
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    check "GPU DRIVER still working" ok
else
    check "GPU DRIVER still working" bad "(it should NOT have been removed)"
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "Reset complete. REBOOT (or at least log out and back in) before testing --"
    echo "the docker group only really leaves your session on a new login."
else
    echo "Some checks failed -- see the FAIL lines above." >&2
    exit 1
fi
