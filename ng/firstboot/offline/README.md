# Offline first-boot pool

Bookworm **arm64** `.deb`s and CPython **3.11** wheels so a packed card can
install Gong-NG **without apt or PyPI**.

| Path | What |
|------|------|
| `Packages` / `Packages.gz` | `file://` apt index (`deb [trusted=yes] file:… ./`) |
| `pool/*.deb` | mpv, Flask stack, venv/pip, gpio, avahi, nftables + Depends |
| `wheels/*.whl` | `flask`, `waitress`, `gpiozero`, `lgpio` and their deps |

Refresh on an aarch64 Bookworm Pi (needs network **once**):

```bash
sudo ./ng/firstboot/vendor-offline.sh
```

Do not put `gong-firstboot.toml` (Wi-Fi secrets) in this tree.
