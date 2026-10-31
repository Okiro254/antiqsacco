# Public access while hosting locally

The SACCO database stays on this computer. The production web server listens only on `127.0.0.1:8080`; Cloudflare Tunnel provides HTTPS access without router port forwarding. Require Cloudflare Access authentication in front of the hostname. Do not use a Quick Tunnel or expose Flask/Waitress directly to the internet.

## Prepare the local server

From PowerShell in this project folder:

```powershell
python -m pip install -r requirements.txt
python .\run_public.py
```

On first start, `run_public.py` creates `.env` with a random `SECRET_KEY`. Keep `.env` private and backed up securely; it is excluded from Git. The server must remain running, and this computer must stay awake and connected for the public site to work.

## Create a protected public hostname

1. Add your domain to Cloudflare and enable Cloudflare Zero Trust.
2. In Zero Trust, create an Access application for a hostname such as `sacco.yourdomain.com`. Add an allow policy for only the members/staff identities you intend to authorize. Keep the public policy deny-by-default.
3. Install `cloudflared` on the host computer:

```powershell
winget install --id Cloudflare.cloudflared --exact
```

4. Authenticate and create a named tunnel:

```powershell
cloudflared tunnel login
cloudflared tunnel create antiq-sacco
cloudflared tunnel route dns antiq-sacco sacco.yourdomain.com
```

5. Create `%USERPROFILE%\.cloudflared\config.yml`, replacing the UUID and credentials path with the values printed by `tunnel create`:

```yaml
tunnel: YOUR-TUNNEL-UUID
credentials-file: C:\Users\YOUR-WINDOWS-USER\.cloudflared\YOUR-TUNNEL-UUID.json
ingress:
  - hostname: sacco.yourdomain.com
    service: http://127.0.0.1:8080
  - service: http_status:404
```

6. In a second PowerShell window, run:

```powershell
cloudflared tunnel run antiq-sacco
```

7. Visit `https://sacco.yourdomain.com`. Cloudflare Access should authenticate/deny users before the application login page. Keep both the Waitress and tunnel processes running.

## Before inviting members

- Replace the initial shared member password with unique temporary passwords and require first-login changes.
- Finish the `Major` super-admin setup, then create individual staff accounts; do not share the demo admin account.
- Restrict Cloudflare Access to named users. Application passwords remain required after Access.
- Keep Windows and Python updated, use a dedicated Windows account, and ensure the project and `.env` are readable only by authorized operators.
- Make regular encrypted backups of `instance/sacco.db` to a separate device/location and test restoration.
- This local-hosted arrangement is unavailable when the PC, internet, or tunnel is down. It is not a substitute for reviewed production operations, disaster recovery, or regulatory/security assessment.
