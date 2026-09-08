# Free Cloudflare quick tunnel (PC must stay on)
# Install once: winget install Cloudflare.cloudflared
# Then start the app: python -m companyresearch
# Then run this script in another terminal.

cloudflared tunnel --url http://127.0.0.1:8787
