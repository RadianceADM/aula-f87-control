# Arch Linux package (AUR)

> **Status:** not published yet. AUR account registration was paused when this was written
> (October 2026). Until then, build it locally with `makepkg -si` (see below).

`PKGBUILD` builds the latest release from its GitHub tag and installs:

- the app (`aula-f87-control`, `aula-f87-control-gui`),
- the udev rule (`/usr/lib/udev/rules.d/70-aula-f87.rules`),
- the menu entry and the icons.

Start at login turns itself on the first time the app runs.

## Test locally

```sh
cd packaging/aur
makepkg -si
```

## Publish or update on the AUR

You need an [AUR account](https://aur.archlinux.org/register) with your SSH key added.

```sh
git clone ssh://aur@aur.archlinux.org/aula-f87-control.git aur-aula-f87-control
cp packaging/aur/PKGBUILD packaging/aur/.SRCINFO aur-aula-f87-control/
cd aur-aula-f87-control
git add PKGBUILD .SRCINFO
git commit -m "Update to $(sed -n 's/^pkgver=//p' PKGBUILD)"
git push
```

## For each new release

1. Set `pkgver` (and reset `pkgrel=1`).
2. Run `updpkgsums` to refresh `sha256sums`.
3. Run `makepkg --printsrcinfo > .SRCINFO`.
4. Publish as described above.
