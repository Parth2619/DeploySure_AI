# Running DeploySure on AWS

Read this first: DeploySure runs the code of the apps it analyzes (pytest, the apps, a browser). It has no login of its
own. Behind this setup it is protected by a web password (nginx) and your firewall. Use dummy apps only, restrict the
firewall to your own IP while presenting, and delete the server afterwards.

Status: tested in an Ubuntu 24.04 container (Python 3.12) on 20 Oct 2026. The whole test suite passed there (407
passed, 1 skipped), and with the nginx config from this folder the password check, the folder list and a full streamed
analysis with a real Chromium all worked. Not tested: a real EC2 server, the systemd service and `setup.sh` itself.
Do a trial run on the server a day before the demo.

## What you need

- An AWS account with a card.
- An EC2 instance: Ubuntu 24.04, `t3.medium` (4 GB RAM), 30 GB disk. Chromium and two copies of an app do not fit in the 1 GB free tier size.
- A key pair (`.pem` file) to log in.
- A security group: SSH (22) from your IP only, HTTP (80) from your IP only (or from `0.0.0.0/0` if you accept the password as the only protection).
- Your Groq key, typed when the setup script asks. It is stored in `/etc/deploysure.env`, never in the code.
- About $1 a day while running. Stop or terminate the instance after the demo.

## Steps

1. **Launch the server.** AWS Console, EC2, Launch instance. Name `deploysure`. Image: Ubuntu Server 24.04 LTS. Type: `t3.medium`.
   Key pair: create one and download it. Network: create a security group with the two rules above. Storage: 30 GB. Launch.
2. **Note the public IP** from the instance page (an Elastic IP keeps it fixed if you stop and start the server).
3. **Pack the code** on your laptop (PowerShell, from `D:\STUDY\FAAI\Project\DeploySure AI`). This leaves out `.venv`, `.env` and saved apps:

```powershell
tar -czf deploysure.tgz --exclude=.venv --exclude=.env --exclude=apps --exclude=__pycache__ --exclude=.pytest_cache --exclude=demo_apps/tinyshop_live deploysure
```

4. **Copy it up and log in** (use your key file and the server's IP):

```powershell
scp -i C:\path\to\key.pem deploysure.tgz ubuntu@<PUBLIC_IP>:~
ssh -i C:\path\to\key.pem ubuntu@<PUBLIC_IP>
```

5. **On the server**, unpack and run the setup (it asks for the Groq key and a web login):

```bash
tar -xzf deploysure.tgz
bash ~/deploysure/deploy/setup.sh
```

6. **Open** `http://<PUBLIC_IP>/` in a browser and log in with the name and password you chose.

## Add the PriceRight demo app on the server

The repo `Parth2619/priceright-demo` is public, so the server can download it. In DeploySure click **Connect app**, type
`https://github.com/Parth2619/priceright-demo` in **GitHub link** and click **Connect app**. DeploySure keeps a copy and
checks GitHub every few seconds. On stage, push the buggy commit from your laptop (`presentation\github_demo.ps1 bug`),
and it appears and is analyzed by itself. Only public GitHub repositories work with the link. **Browse** shows the
server's own folders, not your laptop.

## Useful commands on the server

```bash
sudo systemctl status deploysure        # is it running
sudo journalctl -u deploysure -n 50     # its log
sudo systemctl restart deploysure       # after changing code or the key (edit /etc/deploysure.env with sudo)
```

## If something fails

- Page does not load: check the security group allows port 80 from your IP, and `sudo systemctl status nginx`.
- "Bad gateway": the app is not running, see `journalctl` above.
- Browser checks say Chromium could not start: run `~/deploysure/.venv/bin/python -m playwright install --with-deps chromium` again.
- Progress does not update live: nginx buffering. The provided config turns it off, check `nginx -t` passes.

## Limits

- HTTP only. The password travels unencrypted, so only use a password you use nowhere else. For HTTPS you need a domain name and a free certificate (certbot).
- One analysis at a time, same as on the laptop.
- Not for real projects or real data. Dummy apps only.
