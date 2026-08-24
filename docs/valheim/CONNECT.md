# How to join the Valheim server

This takes about five minutes, one time. After that, joining is two clicks.

The server isn't open to the whole internet — it only accepts connections from
a private network called a "tailnet." That's why there are a couple of setup
steps before you can play. You'll need:

- A share link from whoever runs the server
- The server address and password (also from them) — write them here for
  reference:

  ```
  Server address: ______________________________
  Server password: _____________________________
  ```

---

## Step 1 — Create a Tailscale account

Go to **[tailscale.com/start](https://tailscale.com/start)** and sign up using
**Google, Microsoft, GitHub, or Apple** — whichever you already have. There's
no new password to create, and the free plan is all you need.

## Step 2 — Install Tailscale

Go to **[tailscale.com/download](https://tailscale.com/download)**, download
the version for your computer, and install it. When it opens, sign in with the
account you just created.

You'll know it worked when the Tailscale icon (in your system tray, near the
clock, or in your menu bar at the top of the screen) says **Connected**.

## Step 3 — Accept the share link

Open the share link you were given while signed in to Tailscale, and click
**Accept**.

This is the step that actually makes the server visible to you — without it,
Tailscale will say Connected but Valheim still won't be able to reach the
server.

## Step 4 — Join the server in Valheim

1. Start Valheim and select your character.
2. Click **Join Game**.
3. Click **Join IP** at the bottom of the screen.
4. Type in the server address you were given (see the checklist at the top),
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

You may not have finished Step 3. Ask whoever runs the server to check
[login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines)
for a device named `valheim` and confirm you're listed as someone it's shared
with. If not, ask for a new share link — they expire after 30 days.

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
