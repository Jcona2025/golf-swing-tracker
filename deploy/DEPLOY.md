# SwingLogger — VPS Deploy

Target: Ubuntu VPS already running nginx (alongside the Killineer site),
serving the app at `swinglogger.baselinetech.ie`.

## 1. DNS

Point `swinglogger.baselinetech.ie` at the VPS IP (A record). Wait for
propagation (`dig swinglogger.baselinetech.ie` should return the VPS IP).

## 2. Pull code & install

```bash
ssh you@vps
cd ~
git clone https://github.com/Jcona2025/golf-swing-tracker.git swinglogger
cd swinglogger
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Sanity check
python -c "import app; print('ok')"
```

## 3. systemd service

```bash
# Replace __USER__ and __HOME__ in the service file (root home is /root, not /home/root)
sed -e "s/__USER__/$USER/g" -e "s|__HOME__|$HOME|g" deploy/swinglogger.service \
    | sudo tee /etc/systemd/system/swinglogger.service
sudo systemctl daemon-reload
sudo systemctl enable --now swinglogger
sudo systemctl status swinglogger    # should be 'active (running)'
curl -I http://127.0.0.1:8001/       # should return 200
```

## 4. nginx vhost

```bash
sudo cp deploy/nginx-swinglogger.conf /etc/nginx/sites-available/swinglogger
sudo ln -s /etc/nginx/sites-available/swinglogger /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 5. SSL via Let's Encrypt

```bash
sudo apt-get install -y certbot python3-certbot-nginx   # if not already installed
sudo certbot --nginx -d swinglogger.baselinetech.ie
```

Certbot rewrites the nginx vhost to add `listen 443 ssl` + cert paths
and sets up auto-renewal. Test:

```bash
curl -I https://swinglogger.baselinetech.ie/
```

## Updating after a code change

```bash
ssh you@vps
cd ~/swinglogger
git pull
sudo systemctl restart swinglogger
```

## Logs

- App: `~/swinglogger/error.log`, `~/swinglogger/access.log`
- nginx: `/var/log/nginx/swinglogger.{access,error}.log`
- systemd: `journalctl -u swinglogger -f`
