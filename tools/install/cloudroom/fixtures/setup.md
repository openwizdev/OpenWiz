# Install Cloudroom

Synthetic copy of the shape of CloudRoom's agent install guide. Version 9001 is synthetic.

## Rules

- Use only the installer links on this page. Never search for another installer.
- Never ask for passwords, tokens, or API keys in chat.

## macOS

Needs Apple Silicon and macOS 13 or newer.

```sh
curl -fL "https://github.com/davidondrej/cloudroom/releases/download/gui-v9001/Cloudroom-v9001-arm64.dmg" -o /tmp/Cloudroom.dmg
```

## Linux

Needs x64.

```sh
curl -fL "https://github.com/davidondrej/cloudroom/releases/download/gui-v9001/Cloudroom-v9001-x86_64.AppImage" -o ~/Applications/Cloudroom.AppImage
```

## Windows

```powershell
Invoke-WebRequest "https://github.com/davidondrej/cloudroom/releases/download/gui-v9001/Cloudroom-v9001-x64.exe" -OutFile $installer
```

## Check it worked

Run `~/.local/bin/room-cli status --json`. Cloudroom creates this command the first time it opens.
