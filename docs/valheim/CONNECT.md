# How to join the Valheim server

This takes about five minutes, one time. After that, joining is two clicks.

The server isn't open to the whole internet — it only accepts connections from
a private network called a "tailnet." That's why there are a couple of setup
steps before you can play. You'll need:

- The invite email from whoever runs the server (sent to the email address you
  gave them)
- The server address and password (also from them) — write them here for
  reference:

  ```
  Server address: ______________________________
  Server password: _____________________________
  ```

---

## Step 1 — Accept the invite email

Check your email for an invite from Tailscale. Open it and click the button to
accept.

If you don't see it, check spam, or ask whoever runs the server to resend it.

## Step 2 — Create your Tailscale account

The invite link takes you to a sign-up page. Sign up using **Google,
Microsoft, GitHub, or Apple** — whichever you already have. There's no new
password to create.

## Step 3 — Install Tailscale

Go to **[tailscale.com/download](https://tailscale.com/download)**, download
the version for your computer, and install it. When it opens, sign in with the
account you just created.

You'll know it worked when the Tailscale icon (in your system tray, near the
clock, or in your menu bar at the top of the screen) says **Connected**.

## Step 4 — Join the server in Valheim

1. Start Valheim and select your character.
2. Click **Join Game**.
3. Click **Join IP** at the bottom of the screen.
4. Type in the server address you were given (Step 2 in the checklist above),
   for example:

   ```
   100.x.y.z:2456
   ```

5. Type in the server password when asked.

You will **not** find this server by browsing the public server list — that's
expected. Always connect using **Join IP**.

> **After this first time:** the server will show up under **Favorites** in
> Valheim, so future sessions are just: check Tailscale says Connected → open
> Valheim → click the server under Favorites.

---

## If something doesn't work

**Nothing happens / it just spins on "Connecting..."**

Check that Tailscale says **Connected**. Click the Tailscale icon to check —
it sometimes disconnects after your computer restarts or an update.

**Tailscale says Connected, but Valheim still can't reach the server**

You may not have finished Step 1. Go to
[login.tailscale.com/admin/users](https://login.tailscale.com/admin/users) —
if your name/email isn't listed, the invite wasn't completed. Ask for a new
invite email.

**"Incorrect password" even though you're sure it's right**

Remove the server from your Favorites list, add it again with **Join IP**,
and type the password fresh — Valheim sometimes reuses an old saved password
instead of the new one you typed.

**"Version mismatch" or you get disconnected immediately after joining**

Your copy of Valheim needs an update. Let Steam finish updating and try again.
If it still happens, the server itself needs updating — let whoever runs it
know.

**Still stuck?**

Message whoever runs the server with:
1. Which step you got stuck on
2. Whether Tailscale says Connected or not
3. The exact wording of any error message

---

## Common questions

**Does this slow down my internet, or let the server owner see my traffic?**
No. Tailscale only carries traffic to the one game server — everything else on
your computer works exactly as it did before.

**Can I see or reach anything else on their network?**
No. You only get access to the one server, on the two ports the game needs.
Nothing else on their network is visible to you, and your computer isn't
visible to anyone else on their network either.

**Do I need to keep Tailscale running all the time?**
No — only while you want to play. You can quit it the rest of the time.
