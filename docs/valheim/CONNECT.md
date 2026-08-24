# How to join the Valheim server

You'll do this once, and it takes about five minutes. After that, joining is two
clicks.

The server lives on a private network called a **tailnet** instead of being open
to the internet. That means no one can find or attack it, but it also means you
need a small piece of software (Tailscale) to see it. Tailscale is free, doesn't
route your normal internet traffic, and you only need it running while you play.

---

## Step 1 — Make a Tailscale account

Go to **[tailscale.com/start](https://tailscale.com/start)** and sign up with
Google, Microsoft, GitHub, or Apple. There's no password to create and the free
plan is all you need.

> You need your own account even though you're joining someone else's server —
> that's just how the share works.

## Step 2 — Install Tailscale

Download it for your machine from
**[tailscale.com/download](https://tailscale.com/download)**, install, and sign
in with the account from Step 1.

You'll know it worked when the Tailscale icon in your system tray / menu bar
says **Connected**.

## Step 3 — Accept the share invite

You'll get an invite link. Open it while signed in to Tailscale and click
**Accept**.

This is what makes the game server visible to you. Without it, everything else
looks right but nothing shows up.

## Step 4 — Join in Valheim

1. Start Valheim and pick your character.
2. Click **Join Game**.
3. Click the **Join IP** button at the bottom.
4. Enter the address you were given, which looks like:

   ```
   valheim.<tailnet-name>.ts.net:2456
   ```

5. Enter the server password when prompted.

The server won't appear in the public "Community" server list — that's on
purpose. Always use **Join IP**.

> **Tip:** After joining once, the server shows up under **Favorites**, so
> future sessions are just: make sure Tailscale says Connected → Join Game →
> Favorites.

---

## If something doesn't work

**"Failed to connect" / it just spins**

Check that Tailscale says **Connected** in your tray or menu bar. It sometimes
signs out after a reboot or an OS update.

**Tailscale is connected but Valheim still can't find it**

Confirm you actually accepted the invite from Step 3 — open
[login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines)
and look for a machine named `valheim`. If it isn't listed, ask for a fresh
invite link (they expire after 30 days).

**"Incorrect password"**

Delete the server from your Favorites, re-add it with **Join IP**, and type the
password again — Valheim caches old credentials aggressively.

**"Version mismatch" or you get kicked immediately**

Valheim updated. Let Steam update your game and try again; if it persists, the
server needs the same update and someone will need to bump it.

**Still stuck?** Send whoever runs the server: what step you got to, whether
Tailscale says Connected, and the exact error text.

---

## FAQ

**Does Tailscale slow down my internet or see my traffic?**
No. It only handles traffic to machines on the tailnet — the game server, in
this case. Everything else goes out your normal connection untouched.

**Can I see other machines on their network?**
No. The share gives you exactly one machine — the game server — on two ports.
Nothing else is visible to you, and your machine isn't visible to them.

**Do I have to leave Tailscale running all the time?**
Only while you're playing. Quit it whenever you like.
