# Preparing the client certificate

*[한국어](CA-SETUP.md)*

Before the app can open a DTLS session to an appliance it needs a **client
certificate** signed by the `AC14K_M` intermediate CA. This repository does not
include one, and will not.

## Why it is needed

Samsung's Tizen / RT-OCF appliances ship with a factory ACL that grants one specific
UUID `perm=31` — full permission — over `href=*`. That UUID is published in plain
sight: it appears as `uuid:<UUID>` in the subject DN of the TLS server certificate of
Samsung's cloud gateway. Put that UUID into a certificate signed by `AC14K_M`, and the
appliance treats you as a genuine hub.

**You do not need the appliance's own certificate or key.**

## The app never receives a CA private key

The UUID comes from **Samsung's gateway, not from the appliance**, so it is the same
for every device and every user, and it does not change between calls — verified
against the live gateway. One issued certificate therefore authenticates to every
Samsung appliance in the house: **one per installation, not one per device.**

That is why this app does not take a CA and mint certificates itself. It accepts
**only an already-issued certificate**. The CA private key stays on your computer and
is never sent to the Homey.

> The reference Home Assistant integration does take the CA and issues a leaf per
> config entry. Because the UUID is identical either way, the result is effectively the
> same — this port chose to reduce the amount of sensitive material the app holds.

## What you do

The same instructions are in the app itself, under **Settings → Apps → SmartThings
Local**. Until a certificate is stored, the add-device screen points you there instead
of failing later.

### 1. Issue a certificate (once, on your computer)

> **This repository does not include the CA bundle it needs.** For an example of how to
> obtain it — including fetching the `AC14K_M` certificate and key and verifying that
> they pair — see the `smartthings-local` protocol project's
> [`setup_cert.py`](https://github.com/QuiteYellow/SmartThings-Local/blob/main/setup_cert.py).
>
> Quoting upstream: *"This repo doesn't include the needed CA bundle. For an example of
> how to obtain it, including fetching the AC14K_M cert and key and verifying they
> pair, see the `smartthings-local` protocol project's
> [`setup_cert.py`](https://github.com/QuiteYellow/SmartThings-Local/blob/main/setup_cert.py)."*
> — [mbillow/localthings](https://github.com/mbillow/localthings)

[`QuiteYellow/SmartThings-Local`](https://github.com/QuiteYellow/SmartThings-Local)'s
`setup_cert.py` automates the whole process. It needs Python 3 and the `openssl` CLI.

```sh
git clone https://github.com/QuiteYellow/SmartThings-Local.git
cd SmartThings-Local
python3 -m venv .venv && .venv/bin/pip install pyOpenSSL

# TARGET_IP is optional. Supply it and the script verifies against a real
# appliance before you paste anything.
OUT_DIR=./certs TARGET_IP=192.168.1.90 \
  .venv/bin/python setup_cert.py --test
```

What the script does:

| Step | What happens |
|---|---|
| 1 | Fetches the `AC14K_M` bundle (one private key, four certificates) from a public mirror, splits it, and checks that the certificate and key moduli match |
| 2 | Reads `uuid:<UUID>` out of the server certificate subject at `connect-v2.samsungiotcloud.com:443` |
| 3 | Generates an RSA-2048 key, builds a CSR carrying that UUID in CN/OU/SAN, and signs it with `AC14K_M` using **SHA-1** |
| 4 | With `--test`, performs a DTLS handshake against the appliance and issues `GET /oic/sec/acl`. **`2.05` means the certificate was accepted** (`4.01` means refused) |

### 2. Paste into the app

Of the files written to `certs/`, **only two** are needed.

| File | Field in the app |
|---|---|
| `client_fullchain.pem` | Certificate chain |
| `client.key` | Private key |

`client.pem` — the leaf on its own — **will not work.** The appliance needs the chain
to validate the leaf against. The app detects this case and says so.

The app validates what you paste before storing it: that the certificate and key are a
pair, that the subject carries a `uuid:` token, that the chain holds at least two
certificates, and that nothing has expired. If validation fails, the previously stored
value is left alone.

Once saved, the settings page shows the identifier UUID, the expiry date and the chain
length, and a **Compare with Samsung's gateway** button checks the stored UUID against
what appliances currently expect. That check has its own button because a mismatch is
the one failure mode that looks exactly like a broken network while actually requiring
a re-issued certificate.

### 3. Add an appliance

**Devices → Add device → SmartThings Local** → enter the appliance's IP address. The
port is detected automatically.

## Security notes

- **The `AC14K_M` CA private key is public.** It is an intermediate CA that Samsung
  distributed into the trust store of every appliance, and it has been publicly
  available for years. Anyone on the same LAN can therefore control these appliances
  the same way. That is the firmware's design, not a risk this app introduces, and the
  only mitigation is not putting the appliances on a network you do not trust.
- **Keep `client.key` private.** Whoever holds it can control your appliances from the
  same network.
- The reach is **your own appliances, on your own LAN.** There is no outbound path.
- `certs/`, `*.pem` and `*.key` are in `.gitignore` in both this repository and
  `SmartThings-Local`. Check `git status` before committing anyway.
- The app never returns a stored PEM to the settings page. It exposes only the metadata
  the status display needs: UUID, expiry, chain length.

## A note on distribution

For the official Homey App Store, **a UI that asks the user to paste a private key is a
review risk.** The leaf-only model helps, since the app never handles a CA private key,
but asking Athom before submitting is the safer course. The reference integration
shipping through HACS rather than Home Assistant core is a constraint of the same kind.
