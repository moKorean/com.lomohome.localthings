# TP1X_REF_21K combination-fridge doors

The aggregate `/doors/vs/0` answered GETs and OBSERVE registration but sent no
subsequent changes in the recorded tests. The individual `/door/cooler/0` and
`/door/freezer/0` resources did send changes. Subscribing only to the aggregate
left Homey's contact alarm stale, including after a door closed. On the
tested installation, changes could wait for the five-minute summary poll.

## Measured encoding

Nine user-confirmed positions, covering both opening orders, were checked by
successful direct GETs. The latest individual push values matched those GETs in
all nine samples. The raw freezer resource is not the physical freezer contact:

| Physical cooler | Physical freezer | Raw cooler | Raw freezer |
| --- | --- | --- | --- |
| closed | closed | Close | Close |
| open | closed | Open | Open |
| open | open | Open | Close |
| closed | open | Close | Open |

For these four settled positions, the raw cooler value matched the physical
cooler door, and XOR of the raw values appeared to match the physical freezer door.
The ajar tests below disprove that mapping in general. The combined
`alarm_contact` is OR of the two raw values. If the fridge and combined
alarm are both on, the physical freezer state is unknown.
The cached aggregate is excluded from this calculation. A fresh aggregate GET
matched both raw door resources in all nine positions: item 0 is raw freezer,
and item 1 is raw cooler.

## Implementation and scope

- Gate the door handling and new read-only fridge contact on model prefix
  `TP1X_REF_21K`, exactly the two individual door paths above, and exactly two
  items (IDs 0 and 1) in the aggregate. The prefix was read from paired Homey settings.
- Subscribe to both individual resources instead of the aggregate on that surface.
- Publish the fridge contact and combined alarm from the same snapshot after three seconds
  without another individual-door notification. The largest captured gap between
  paired changes was 2.23 seconds. Polling cannot bypass a pending debounce.
- If only one resource notified, read `/doors/vs/0` once to confirm both raw
  states. If that read fails or is incomplete, keep the last published status
  until a complete update. Discard the result if a newer push arrives during the read.
- Add a Fridge door GUI contact, history and Flow cards. Preserve the
  combined alarm and its Flow capability ID. The freezer resource still feeds
  the combined alarm; no separate freezer contact or Flow card is exposed.
- Keep the polling rules unchanged. A change in subscriptions can affect which
  existing interval the app uses. Other model surfaces retain their existing logic.

The standalone freezer has an `onedoorfreezer` resource and does not match this
two-door gate. The US reference fixture has the same board prefix but a third
door, `/door/cvroom/0`. Its push behavior and door encoding are untested, so the
existing alarm logic and subscriptions are kept there too.

## Evidence and limits

`tests/fixtures/sequences/combi_door_control_TP1X_REF_21K.json` contains the
sanitized measured states and notification timings, not a fabricated full-device
dump. Tests replay these timings through the real device notification/apply path
with a deterministic clock, and verify the fridge contact and combined alarm for all nine settled positions.
A replay of the ambiguous ajar readings also verifies that neither reports an
independent freezer state. They also cover a lost push, a failed or incomplete
verification GET, a new push during GET, the third-door regression, and timer cleanup.

The three-second quiet period can suppress shorter pulses. A verification GET
adds latency on single-source updates; steady-state polling cadence still follows
the existing rules. This does not detect a door transition if every push for it
is lost: the next scheduled poll remains the fallback.

The diagnostic transport was `smartthings-local` 0.1.25. The locally installed
earlier patched app (including the experimental freezer contact) was tested on one TP1X_REF_21K two-door unit. The two contacts and
combined alarm agreed with all four physical positions, including returning to
closed. The freezer status lagged briefly when opening the second door. This
test verifies settled states; it did not measure exact latency, distinguish
push from GET/poll, or exercise Flow triggers.

## Live finding: fridge ajar is indistinguishable from both doors open

On 2026-11-23 the freezer stayed physically closed while the fridge door was
held ajar with its light on. Homey repeatedly indicated both doors open. Direct
reads in that position returned `Open` from `/door/cooler/0` and `Close` from
`/door/freezer/0`; a direct aggregate read also returned ID 0 `Close` and ID 1
`Open`. These are the same values measured with both doors physically open in
the control sequence. Opening the fridge door fully, without moving the
freezer door, cleared the false freezer indication in that build. The combined alarm
correctly remained on.

The observed resources cannot distinguish these positions. The decoded
freezer contact can therefore be a false positive. The combined alarm was
correct in this case. In follow-up tests the false freezer indication sometimes
persisted for more than 25 seconds and was still present when the fridge
door was moved to end the test. No time to spontaneous recovery was
established. A longer debounce cannot resolve a held ambiguous state and
would also delay real freezer updates.

In a separate test, the freezer door was held ajar while the fridge stayed
closed. Both individual resources and both aggregate entries returned
`Close` on direct reads. Moving the freezer door farther open and waiting
for the test app to settle did produce an open indication. No switching
distance was measured. In the tested ajar position, there was no open
value for the integration to act on; this does not identify the underlying
physical sensor or firmware cause.

The alarm cannot detect ajar positions that the appliance reports as closed.

## Validation on Homey Pro

The final code (efc9e79) was installed over the earlier test build on one
Homey Pro (2026) and tested on the same two-door unit on 2026-11-23.
Homey's timeline recorded these local times:

| Physical action | Timeline result |
| --- | --- |
| Open and close freezer only | Combined alarm on at 02:51:00, off at 02:51:07; no fridge event |
| Open and close fridge only | Fridge contact and combined alarm on at 02:51:23, off at 02:51:29 |
| Open both, close fridge, then close freezer | Both on at 02:54:32; only fridge contact off at 02:54:40; combined alarm off at 02:54:50 |

The paired device retained the fridge contact and combined alarm; the old
experimental freezer contact was removed. The timeline confirms behavior,
not the time from door movement to notification. Flow cards were not
exercised in these hardware tests.
