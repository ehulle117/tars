# iSpindel → Mead Log

Mead Log takes readings straight from an [iSpindel](https://www.ispindel.de/) running
[GravityMon](https://github.com/mp-se/gravitymon) (or the stock iSpindel firmware).

## Set up the device

1. Flash GravityMon and join the home WiFi.
2. Calibrate it (water plus a couple of sugar solutions, checked with the hydrometer), gravity unit **SG**.
3. Push target: **HTTP POST**, format **iSpindel**, URL `http://192.168.8.103:8770/api/ispindel`
   (the mead LoadBalancer; `http://homebrew.case.local/api/ispindel` goes through Nginx Proxy Manager and works too).
4. Interval 900 s (15 min).

It shows up on **Devices** (`/devices`) after its first post.

## Use it on a batch

Batch → **Details → iSpindel**: type the device's name. While that batch is primary/secondary/aging:

- each post updates the device (gravity, temperature, battery, WiFi) on `/devices`;
- at most one reading an hour is logged on the batch, noted `iSpindel` (they sit in their own collapsed list);
- the "re-check gravity" prompt disappears from Up next and Discord while it's reporting;
- three days of hourly points within 0.001 count as stable (the hand-reading rule still needs a week);
- quiet for 12 h, or battery under 3.5 V, becomes a task on the dashboard and in Discord.

## Calibration offset

On `/devices`, set the SG offset if it disagrees with the hydrometer (reads 1.012 when the hydrometer says
1.010 → `-0.002`). It applies to new posts only.

## Payload

The iSpindel JSON format: `name`, `gravity` (SG, or °Plato if `gravity-unit` is `P` or the value is above 1.5),
`temperature` + `temp_units` (`C`/`F`/`K`), `battery`, `angle`, `RSSI`, `interval`. Anything else is ignored.
