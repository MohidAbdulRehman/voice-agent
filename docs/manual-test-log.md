# Manual phone test log

The four scripted calls from [`testing.md` §7](specs/testing.md), made to the real number, **+1 (484) 317-5014**. They cover what automated tests can't: real phone audio, voice quality and latency.

The free plan has 50 inbound minutes a month, so each call should stay under about 3 minutes.

## Before the calls

- Check that `lk agent status` shows **Running** or **Sleeping**.
- If it shows Sleeping, wake the agent with a short Agent Console session (LiveKit Cloud → Agents → the agent → **Launch Console**). Otherwise the first call waits 10–20 seconds for the agent to start.
- Make sure **Agent observability** is on (LiveKit Cloud → Settings → Data and privacy), so each call's recording and transcript are kept.
- Use made-up details only. The dashboard and API are public.

## After each call

- **Dashboard:** the Patients tab should show the record, and the [Calls tab](https://riverside-intake.vercel.app/dashboard/#calls) the call's status, summary and transcript. Or use the API: `GET /patients?phone_number=…` and `GET /calls`.
- **Recording:** LiveKit Cloud → Sessions → the call → **Agent insights**, for the audio and per-turn timings.
- **Log it:** write down the result and notes on voice quality and latency below.

## Scripts

1. **Happy path + appointment (English).**
   - Register as "Jordan Rivera", born March 5th, 1990, male.
   - When Maya asks whether the number you're calling from is the best one, say no and give 512-555-0123.
   - Address: 12 Oak Street, Austin, Texas, 78701.
   - Decline the optional details, confirm the read-back, then book the first appointment offered.
   - **Expect:** "You're all set, Jordan.", a `registered` call, and one appointment.
2. **Correction, invalid date, start over.**
   - Give the address first, then the name "Sam Davies".
   - Give a birth date in the future. Maya should ask for it again.
   - Then say "Actually, it's spelled D-A-V-I-S".
   - Before the read-back, say "Can we start over?", then hang up.
   - **Expect:** the future date asked for again on its own, the spelling corrected, a fresh start, and no patient saved.
3. **Returning caller.**
   - Call again and give the number from call 1 (512-555-0123).
   - **Expect:** "It looks like we already have a record for Jordan Rivera. Would you like to update your information instead?"
   - Say yes and change the city to Round Rock.
   - **Expect:** only the city changes, and the call shows `updated`.
4. **Spanish.**
   - Start with "Hablo español".
   - Register in Spanish with made-up details and a new number, such as 512-555-0125.
   - **Expect:** Maya switches to Spanish for everything, including the read-back and the goodbye ("Ya está todo listo, …"), and the preferred language is saved as Spanish.

## Results

| # | Date | Scenario | Result | Voice quality and latency | Evidence |
|---|---|---|---|---|---|
| 1 | | Happy path + appointment | Pending | | |
| 2 | | Correction, invalid date, start over | Pending | | |
| 3 | | Returning caller → update | Pending | | |
| 4 | | Spanish | Pending | | |

## Checks without phone minutes

These ran before the phone calls:

| Date | How | What happened |
|---|---|---|
| 2026-09-25 | Text console, local database | Registration and an appointment worked end to end. This run found a silent hang-up and a skipped optional-details question, both fixed in 89be49d. |
| 2026-09-28 | Voice console, local database, recorded with `--record` | The registration and appointment were saved. The read-back was read out word for word, and the goodbye was "You're all set, …". This run found two problems: after two unusable phone numbers, the agent skipped the lookup (fixed in 2d9743e), and speech-to-text misheard "male" (fixed with keyterm hints). |
| 2026-09-28 | Agent Console in the browser, talking to the agent deployed on LiveKit Cloud | It worked. There was some latency, partly from the distance between the tester in Pakistan and the agent in Virginia, and interrupting Maya works as designed. |
