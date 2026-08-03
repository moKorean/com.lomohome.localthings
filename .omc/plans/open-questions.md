# Open questions

## device-comm-layer - 2026-08-03 (revised after Architect/Critic review)

- [ ] Were the missing initial notifications lost at the appliance's input (C1,
      unpaced burst), silently no-oped by a token collision (C2), or received and
      discarded by this app (C3)? — Three hypotheses, one symptom, three different
      fixes. Discriminator is now the **round-decay experiment**, not an app restart:
      with `OBSERVE_REFRESH_S` lowered in a dev install, record `notified_hrefs` per
      round on one AC. Monotonic decay across rounds on one session ⇒ C2; flat and low
      from round 1 ⇒ C1 or C3, which commit 3's `dispatch_drops`/`observe_non_205`
      counters then separate. (The previous restart discriminator is void: it assumes
      `on_uninit` ran, and `const.py:51` records unclean shutdown as routine.)
- [ ] Does a direct GET of each of the seven AC card hrefs return the same fields as
      that href's entry inside the `/device/0` Collection? — Item 3's targeted-read
      design rests on this entirely. `/oic/d` is standing proof the two views can
      differ. Read-only measurement via `/read-resource` **with `host` set**, diffed
      against `/resources?host=<IP>&raw=1`. Hard prerequisite; if any href is thinner
      it stays on the full-read path.
- [ ] How long does each of the seven AC card hrefs actually take to report a written
      value? — `WRITE_SETTLE_S = 4.0` gates notifications while `_AC_SETTLE_S = 2.5`
      gates the verification poll, and the poll path is not gated at all. One of the
      two is wrong, and a single global constant for seven resources is itself an
      inference. Item 5, via timed single-href `/read-resource` calls; `/write-resource`
      does not set `_settling`, so it measures the appliance cleanly and a second
      experiment is needed for the app-level race.
- [ ] How much settle margin was the 2-8 s full `/device/0` read accidentally
      providing, and does RT-OCF regenerate a Collection's representation per Block2
      block? — Item 3 removes that wall-clock time. The 2-8 s is a measured *read
      duration*; the settle margin it implies is unmeasured, and whether a later block
      already reflects a newer state is unknown. If it does, a full read's "after"
      value is not a single point in time at all.
- [ ] Should `_on_notification` keep **dropping** a rep that arrives inside the settle
      window, or **defer** and apply it when the window closes? — Today it drops
      (`device.py:314-318`), after crediting `_notified`, so channel health is counted
      correctly but the value is lost until the next read. That loss is itself a way to
      manufacture the "push missed a change" signal a demotion rule would watch for.
      Item 5 must decide; leaving it undecided is not defensible for a value-loss path.
- [ ] Is `OBSERVE_SUCCESS_FRACTION = 0.8` right for this hardware? — Item −1 restores
      it because a verdict that cannot fail is worse than a wrong threshold, but 0.8 is
      inherited from the reference and has never been measured here. Derive it from the
      per-round registration counts that the round-decay experiment and commit 3
      produce.
- [ ] What is an air conditioner's actual request ceiling? — `dtls_session.py:58-63`
      records dryer ~14 req/s and oven ~8 req/s and says 5 req/s is a conservative
      untuned default to be tuned "once the ceiling is measured empirically". No AC
      ceiling has ever been measured, so both the burst hypothesis (C1) and every cost
      model in the plan rest on a default rather than a number.
- [ ] Is `OBSERVE_REFRESH_S = 6 h` the right interval for this hardware, or just the
      library's suggestion? — Once `subscribe_sends` exists and the round-decay series
      has run, the interval at which RT-OCF actually ages out registrations can be
      derived instead of assumed.
- [ ] Do nine simultaneous poll loops actually cost anything on Homey Pro hardware?
      — Cut from the plan and parked here. Sessions are per host with per-host locks,
      so no appliance-side rate limit is being violated; any cost is Homey CPU and LAN
      concurrency, and that is unmeasured. Adding jitter without the number would be
      inference. `last_poll_duration_s` ships in commit 3 anyway, so the measurement
      stays available at no cost.
- [ ] On what signal should a device be demoted from push, and after how many
      occurrences? — The whole demotion item was cut: its evidence base moved (27/26/3/6
      no longer reads as "idle but healthy") and the settle window can manufacture the
      signal it would watch. `sweep_detected_misses` plus a 24 h idle baseline ship as
      data; the verdict, the threshold N, and whether demotion also deregisters are all
      for the re-plan.
- [ ] Should the three surfaces that render `_observing` in the present tense
      (`/diagnostics`, the settings panel's `status`, the `is_pushing` Flow condition)
      be relabelled? — The flag only claims that a verdict passed up to 6 h ago, and
      the panel's "N subscriptions" is a set count that cannot show the C2 leak. No
      relabelling in this plan; it belongs with the demotion re-plan, but the Flow
      condition is the surface most likely to be misread as "push is alive now".
