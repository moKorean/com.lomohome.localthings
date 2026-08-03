# Preparing the client certificate

**English** · **[한국어](CA-SETUP.md)**

> **You almost certainly do not need this.** Since 1.0.0 the app issues its own client
> certificate on first run — install it, open **Devices → Add device**, and you are done.
> This document is for the optional case of supplying a certificate signed by Samsung's
> `AC14K_M` CA instead. A certificate you paste takes precedence and the app will never
> replace it.
>
> Why the app can issue its own: the appliance checks the identifier carried in the
> certificate, not who signed it. Measured against an air conditioner and a
> refrigerator, both of which accepted a certificate signed by a key generated on the
> spot. Follow this guide if you would rather hold a Samsung-signed certificate, or if
> an appliance update ever stops accepting the app's own.

If you do want your own: you run one script on your computer, it produces two files, and
you paste their contents into the app's settings.
You do not repeat it per appliance.

It takes about ten minutes, and this guide assumes you have never used a command line.

---

## Why this is needed

Samsung appliances do not let anyone control them locally. They only accept a connection
from something that presents a **certificate proving it is a genuine hub**. Creating that
certificate is what this guide does.

The identifier inside the certificate comes from **Samsung's servers, not from your
appliance**, so it is the same for every user and every device. That means **one
certificate for the whole house**.

The app **never receives a CA private key.** It stores only the finished certificate, so
the key used to sign it stays on your computer and is never sent to the Homey.

---

## Step 1 — Check what you need

Two things: **Python 3** and **OpenSSL**. Find your operating system below.

<details open>
<summary><b>macOS</b></summary>

Open Terminal (`Command + Space`, type `Terminal`, press Enter). Paste this and press
Enter:

```sh
python3 --version && openssl version
```

Two lines of output means you are ready — macOS includes both.

If a developer-tools install dialog appears when you run `python3`, click **Install**,
wait for it to finish, then run the command again.

</details>

<details>
<summary><b>Windows</b></summary>

Windows does not include OpenSSL. Installing **Git for Windows** gives you OpenSSL plus
a terminal (Git Bash) where the same commands as macOS and Linux work, so that is the
route this guide takes.

1. **Python** — install from
   [python.org/downloads](https://www.python.org/downloads/). On the first screen of the
   installer, be sure to tick **Add python.exe to PATH**.
2. **Git for Windows** — install from
   [git-scm.com/download/win](https://git-scm.com/download/win). The default options are
   fine.

Then open **Git Bash** from the Start menu and paste this (paste with a right-click):

```sh
python --version && openssl version
```

If `python` errors, try `python3`. If neither works, the PATH box was missed during the
Python install — reinstall Python and tick it.

> Every remaining command in this guide assumes **Git Bash**. PowerShell and Command
> Prompt use different path separators and environment-variable syntax, so the commands
> cannot be pasted there as-is.

</details>

<details>
<summary><b>Linux</b></summary>

In a terminal:

```sh
python3 --version && openssl version
```

If either is missing, install it for your distribution.

```sh
# Debian, Ubuntu, Raspberry Pi OS
sudo apt update && sudo apt install -y python3 python3-venv openssl git

# Fedora, RHEL
sudo dnf install -y python3 openssl git

# Arch
sudo pacman -S --needed python openssl git
```

</details>

---

## Step 2 — Create the certificate

The issuing script lives in a separate project. Fetch it and run it.

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

First fetch the script. Paste one line at a time and press Enter. (Same on macOS, Linux
and Windows.)

```sh
git clone https://github.com/QuiteYellow/SmartThings-Local.git
cd SmartThings-Local
```

Now run it. Putting **one appliance's IP address** in `TARGET_IP` makes the script test
the new certificate against that appliance straight away. If you do not know an address,
delete the `TARGET_IP=192.168.1.90 ` part.

<details open>
<summary><b>macOS · Linux</b></summary>

```sh
python3 -m venv .venv
.venv/bin/pip install pyOpenSSL
OUT_DIR=./certs TARGET_IP=192.168.1.90 .venv/bin/python setup_cert.py --test
```

</details>

<details>
<summary><b>Windows (Git Bash)</b></summary>

Only the paths inside the venv differ — `Scripts` rather than `bin`.

```sh
python -m venv .venv
.venv/Scripts/pip install pyOpenSSL
OUT_DIR=./certs TARGET_IP=192.168.1.90 .venv/Scripts/python setup_cert.py --test
```

</details>

> `pyOpenSSL` is needed **only for the test connection (`--test`)**. If it fails to
> install, the certificate is still created and the script simply skips the test.

**If you do not know an appliance's IP address**: look at the connected-device list in
your router's admin page, or open the appliance in the SmartThings app under Settings →
Information → Network. You do not need it — the app's **Search** finds appliances later.

### Checking it worked

With `--test`, the last lines should include:

```
GET /oic/sec/acl -> 2.05
```

**`2.05` means the appliance accepted the certificate.**

| Output | Meaning | What to do |
|---|---|---|
| `2.05` | Success | Go to step 3 |
| `4.01` | Certificate refused | See [Troubleshooting](#troubleshooting) |
| Test skipped | No `pyOpenSSL`, or no `TARGET_IP` | The certificate was still created. Step 3 is fine |

Four files appear in `certs/`. **Only two** are used.

| File | Used? |
|---|---|
| `client_fullchain.pem` | **Yes** — certificate chain |
| `client.key` | **Yes** — private key |
| `client.pem` | No (the leaf alone, with no chain) |
| `client.csr` | No (an intermediate artefact) |

---

## Step 3 — Paste into the app

Open **Settings → Apps → SmartThings Local** on your Homey. There are two fields.

You are not attaching a file — you are **copying the file's entire contents as text**.

<details open>
<summary><b>macOS · Linux — straight to the clipboard</b></summary>

```sh
# macOS
cat certs/client_fullchain.pem | pbcopy      # paste into: Certificate chain
cat certs/client.key | pbcopy                # paste into: Private key

# Linux (needs xclip: sudo apt install xclip)
xclip -sel clip < certs/client_fullchain.pem
xclip -sel clip < certs/client.key
```

</details>

<details>
<summary><b>Windows (Git Bash) — straight to the clipboard</b></summary>

```sh
cat certs/client_fullchain.pem | clip        # paste into: Certificate chain
cat certs/client.key | clip                  # paste into: Private key
```

</details>

<details>
<summary><b>Any OS — open in an editor and copy</b></summary>

Open the `certs/` folder in your file manager and open each file in a **plain text
editor** such as Notepad or TextEdit. Select everything with `Ctrl + A`
(`Command + A` on macOS) and copy.

Do not open them in a word processor such as Word — it introduces invisible formatting.

</details>

What you paste looks like this. Include the `-----BEGIN` and `-----END` lines.

```
-----BEGIN CERTIFICATE-----
MIIDpTCCAo2gAwIBAgIUJ...
...
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIDkTCCAnmgAwIBAgIUY...
...
-----END CERTIFICATE-----
```

`client.pem` **will not work** — it holds one certificate, with no chain for the
appliance to validate against. The app detects this and says so.

When you save, the app checks that the certificate and key are a pair, that the
identifier is present, that the chain holds at least two certificates, and that nothing
has expired. If any check fails it does not save, tells you why, and leaves the previous
value alone.

On success the status changes to **ready** and shows the identifier, expiry date and
chain length.

---

## Step 4 — Add appliances

**Devices → Add device → SmartThings Local → Search**

The app sweeps your network, finds appliances that answer and identifies each one. It
takes a minute or two.

The search does not find every appliance. If yours is missing, use the **Add by IP
address** button — your subnet is prefilled, so only the last number needs typing.

---

## Troubleshooting

**`openssl: command not found`**
Step 1 was skipped. On Windows, check you are in **Git Bash** and not PowerShell.

**`python3: command not found`** (Windows)
Use `python` instead of `python3`. If neither works, **Add python.exe to PATH** was not
ticked during installation — reinstall Python.

**`GET /oic/sec/acl -> 4.01`** — the appliance refused the certificate
The usual cause is that this appliance runs **older firmware** that does not support this
protocol at all. Try another appliance's IP. Roughly 2022 and later models are in scope.

**`openssl` fails at the signing step (Fedora, RHEL, newer Ubuntu)**
The certificate has to be **SHA-1 signed** because of the `AC14K_M` chain, and
recent distributions' system crypto policy refuses SHA-1 signatures outright. The
issuing script now detects that and retries with a config that permits it
(`SmartThings-Local` issue #19), so **pulling the latest clone fixes it.**

```sh
cd SmartThings-Local && git pull
```

**The test hangs with no response**
Either the IP address is wrong, or the appliance is on a different network — a guest
network, for instance. Your computer and the appliance must be on the same network.

**The app says the certificate chain is required**
You pasted `client.pem`. Paste `client_fullchain.pem` instead.

**The app says the certificate and key do not match**
Either the two fields are swapped, or files from two different runs got mixed. Delete
`certs/` and repeat step 2.

**Will I have to do this again?**
The certificate has an expiry date, ten years out. You would need to re-issue if it
expires or if Samsung changes the identifier. The **Compare with Samsung's gateway**
button in the app's settings tells you whether the stored identifier is still valid —
that check has its own button because a mismatch looks exactly like a broken network
while actually being the one case that needs a new certificate.

---

## Security notes

- **The `AC14K_M` CA private key is public.** It is an intermediate CA that Samsung
  distributed into the trust store of every appliance, and it has been publicly
  available for years. Anyone on the same LAN can therefore control these appliances the
  same way. That is the firmware's design, not a risk this app introduces, and the only
  mitigation is not putting the appliances on a network you do not trust.
- **Keep `client.key` private.** Whoever holds it can control your appliances from the
  same network. Once you have pasted it, you may delete the `certs/` folder — you can
  always issue a new one.
- The reach is **your own appliances, on your own LAN.** There is no outbound path.
- `certs/`, `*.pem` and `*.key` are in `.gitignore` in both this repository and
  `SmartThings-Local`. Check `git status` before committing anyway.
- The app never returns a stored PEM to the settings page. It exposes only the metadata
  the status display needs: identifier, expiry, chain length.

---

## Background — why this works

Nothing below is needed to use the app.

Samsung's Tizen / RT-OCF appliances ship with a factory ACL that grants one specific
UUID `perm=31` — full permission — over `href=*`. That UUID is published in plain sight:
it appears as `uuid:<UUID>` in the subject DN of the TLS server certificate of Samsung's
cloud gateway. Put that UUID into a certificate signed by `AC14K_M` and the appliance
treats you as a genuine hub. **You do not need the appliance's own certificate or key.**

Because the UUID comes from the gateway rather than the appliance, it is the same for
every device and every user and does not change between calls — verified against the live
gateway. That is why this app does not take a CA and mint certificates itself; it accepts
**only an already-issued certificate**.

> The reference Home Assistant integration does take the CA and issues a leaf per config
> entry. Because the UUID is identical either way, the result is effectively the same —
> this port chose to reduce the amount of sensitive material the app holds.

What the script does:

| Step | What happens |
|---|---|
| 1 | Fetches the `AC14K_M` bundle (one private key, four certificates) from a public mirror, splits it, and checks that the certificate and key moduli match |
| 2 | Reads `uuid:<UUID>` out of the server certificate subject at `connect-v2.samsungiotcloud.com:443` |
| 3 | Generates an RSA-2048 key, builds a CSR carrying that UUID in CN/OU/SAN, and signs it with `AC14K_M` using **SHA-1** |
| 4 | With `--test`, performs a DTLS handshake against the appliance and issues `GET /oic/sec/acl`. **`2.05` means the certificate was accepted** (`4.01` means refused) |

Environment variables you can set: `OUT_DIR` (default `./certs/`), `TARGET_IP`,
`TARGET_PORT` (default `49154`), and `UUID` to supply the identifier yourself instead of
looking it up.
