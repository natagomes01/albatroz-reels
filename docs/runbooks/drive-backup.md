# Google Drive backup (one-way)

`shorts backup` sends final renders to Google Drive with `rclone copy`. It only adds and updates
files on Drive. It never deletes on Drive and never syncs back. The Google Drive app on the Mac is
not involved.

## One-time setup (about 10 min)

1. `brew install rclone`
2. `rclone config`
   - `n` new remote, name `gdrive`, storage `drive`
   - scope: `drive.file` (option 3): rclone sees only the files it created
   - client_id: leave blank, or paste an OAuth client from the Google Cloud project used for YouTube
   - log in with the account that will hold the backup
3. Encrypt the config (it holds the Drive token): in `rclone config`, choose `s` (set configuration
   password). Store the password in the Keychain:
   `security add-generic-password -s rclone-config -a "$USER" -w`
   and export it for rclone in your shell profile:
   `export RCLONE_CONFIG_PASS="$(security find-generic-password -s rclone-config -w)"`
4. Test without sending anything:
   `rclone mkdir gdrive:albatroz-media-backup`
   `shorts backup --dry-run`

## On the Windows PC

The same remote, from the PC (where the workshop media lives since 23/10/2026). In PowerShell as
administrator:

1. ```powershell
   winget install --id Rclone.Rclone -e --scope machine --location C:\albatroz\programs\rclone --accept-package-agreements --accept-source-agreements
   ```
   Open a new PowerShell and check `rclone version`.
2. `rclone config`, with the same answers as step 2 above (remote `gdrive`, storage `drive`, scope
   `drive.file`). It opens the browser for the Google login.
3. Encrypt the config (`s` in `rclone config`). Keep the password in the Credential Manager instead
   of the Keychain (the command asks for it):
   `python -m keyring set rclone-config $env:USERNAME`
   and load it in your PowerShell profile (`notepad $PROFILE`):
   `$env:RCLONE_CONFIG_PASS = python -m keyring get rclone-config $env:USERNAME`
4. Test without sending anything: `rclone mkdir gdrive:albatroz-media-backup`, then
   `shorts backup --dry-run`. `shorts doctor` shows `rclone remote` as ok when `backup.auto` is on.

The E: disk is the only copy of the masters on the PC, so `shorts backup --masters` is the backup of
the backup.

## Everyday

- `shorts backup` sends every render; `shorts backup <job>` sends one class; `--masters` also sends
  the camera masters (20 to 40 GB each).
- `backup.auto = true` in `config.toml` runs it after each `shorts render`.
- A re-rendered clip replaces the file on Drive; Drive keeps the old one in its revision history.
- A clip removed with `shorts clean` stays on Drive. Cleaning Drive is always manual.
- If the Google Drive app is in "Mirror files" mode, it downloads this folder back to the Mac. Keep
  it in "Stream files" mode.
