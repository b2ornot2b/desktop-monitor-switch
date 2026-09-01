# macOS event taps

## Two permissions, doing different jobs

| permission | grants | check |
|---|---|---|
| Input Monitoring | seeing events | `Quartz.CGPreflightListenEventAccess()` |
| Accessibility | *suppressing* events | `AXIsProcessTrusted()` |

With Input Monitoring alone, `CGEventTapCreate` still succeeds but the tap is
downgraded to listen-only: returning `None` no longer swallows the event, so
keystrokes reach **both** machines. Both are needed here.

`AXIsProcessTrusted` is not exposed by pyobjc-framework-Quartz; reach it
through ctypes:

```python
import ctypes, ctypes.util
lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
lib.AXIsProcessTrusted.restype = ctypes.c_bool
lib.AXIsProcessTrusted()
```

Permission attaches to the **hosting binary** — your terminal when launched
from a shell — not to the script.

## The Space-switch gesture cannot be suppressed

macOS handles the three/four-finger Space swipe from the raw multitouch stream,
above event taps. A tap can observe it but not stop it. This is not a
permissions problem and no amount of masking changes it.

Confirmed independently: Deskflow/Synergy hit the same wall, and a public
write-up of that investigation tried Hammerspoon `eventtap`, `osascript`
System Events, and Karabiner virtual HID — all filtered or ineffective.

The consequence shaped the whole design. Instead of intercepting the gesture,
give it something useful to switch between: one macOS Space per remote
workspace. macOS performs the switch natively, and the app only observes which
Space became active. "Swipe left off the front to leave" then works for free.

**If you find yourself trying to intercept a Space gesture, stop.** Model the
thing you want as Spaces instead.

## Suppress selectively, or you trap the user

Suppressing *everything* while capturing sounds right and is a trap. With two
displays, swallowing clicks means clicking a window on the other display never
lands, focus never changes, and the capture state sustains itself with no way
out.

The rule here:

- **Pointer motion** — forwarded, never suppressed, so the cursor can always
  leave the shared monitor
- **Keys, clicks, scroll** — suppressed, but only while the pointer is over the
  shared monitor

Any change to capture logic has to preserve at least one escape route.

## Taps get disabled, and you disable them too

The system disables a tap that takes too long, delivering
`kCGEventTapDisabledByTimeout`. Re-enable it — but only if you *want* it live:
disabling a tap yourself fires the same notification, so an unconditional
re-enable turns your own "idle" state back on.

```python
if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
    if self._active and self._tap is not None:
        Quartz.CGEventTapEnable(self._tap, True)
    return event
```

Keep the callback fast, and never let an exception escape it — wrap the body
and pass the event through on error, or a bug in forwarding wedges the user's
input entirely.

## `CGAssociateMouseAndMouseCursorPosition(False)` is global state

It detaches the cursor from the mouse, which is the usual trick for stopping a
local cursor wandering while forwarding deltas. But it is **global**: if the
process dies while it is set, the cursor stays frozen for the whole login
session, and the person has no obvious way to fix it.

Not worth it here — suppressing motion events already keeps the pointer still
where that is wanted. Left available as `freeze_local_cursor`, off by default,
and restored unconditionally on stop.

## Useful event fields

```python
Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventDeltaX)
Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventButtonNumber)
Quartz.CGEventGetIntegerValueField(event, Quartz.kCGScrollWheelEventDeltaAxis1)
Quartz.CGEventGetLocation(event)   # CG coords: origin top-left, y downwards
```

Drop auto-repeats when forwarding: the far side repeats on its own from the
held-down state, so forwarding them doubles up.

Modifiers arrive as `flagsChanged` with no direction. Work out press versus
release from the device-dependent flag bit for that specific key (left shift
`0x0002`, right shift `0x0004`, and so on), which is also the only way to tell
left from right.
