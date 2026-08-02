# Quest Data Request Pipeline

## Scope

This note records the current reverse-engineering findings behind the Reforged
quest bindings and the Party Quest Log's data-loading behavior.

## What is already cached

The quest log/context already exposes the basic record for each quest:

- quest ID and log state;
- location and map-from/map-to IDs;
- marker coordinates;
- completion, primary, and mission-quest flags;
- pointers to encoded name, description, objectives, location, and NPC strings.

Reading the record is therefore different from obtaining readable text. The
text fields are encoded Guild Wars strings and must pass through the native UI
decoder before Python can consume them.

## Legacy request sequence

The legacy GWCA `QuestMgr` resolved three nearby functions from a quest request
anchor:

```text
RequestQuestInfo_Func(quest_id)
RequestQuestData_Func(quest_id, update_markers)
SetActiveQuest_Func(quest_id)
```

`RequestQuestInfoId` called the first two functions in sequence. The old Python
workflow then requested each text field and waited for its ready flag. The
active quest was changed temporarily because the old workflow treated the
request as an active-quest/UI operation, then restored the original quest.

## Reforged binding path

The Reforged native binding exposes the same logical operations through
`PyQuest` and `GLOBAL_CACHE.Quest`:

```text
RequestQuestInfo
RequestQuestName / Description / Objectives / Location / NPC
IsQuest*Ready
GetQuest*
```

The actual native request must run on `GW::game_thread`. The Python action
queue is only a serializer; it is not the native game-thread boundary.

The crash investigation showed the old direct binding path reached
`GW::quest::RequestQuestInfoId` from the Python callback stack. That request
then entered the active-quest hook while Guild Wars was rendering, producing
the `Model closed while in render queue` assertion. The request binding was
subsequently moved behind `GW::game_thread::Enqueue`.

## WASM findings

The WASM retains named quest/challenge cache functions that expose the more
direct internal model:

- `CharCliChallengeGetData` at `ram:80c426ed`;
- `CharCliChallengeGetDescription` at `ram:80c42b22`;
- `CharCliChallengeGetSelected` at `ram:80c42fab`;
- `CharCliChallengeRequestDescription` at `ram:80c437c3`.

These functions demonstrate that Guild Wars has a keyed challenge/quest cache
and direct request/getter operations. They are evidence for a future native
snapshot API, but they are not yet a complete x86 mapping for every quest-log
field in the Reforged module.

### Confirmed WASM cache layout

The decompilation shows that this is a live `CharClient` cache populated by
server callbacks:

```text
CharClient + 0x52c  -> ChallengeDisplay array pointer
CharClient + 0x530  -> allocated capacity
CharClient + 0x534  -> element count
CharClient + 0x538  -> allocation-growth state
ChallengeDisplay     -> 0x34-byte records, sorted by challenge/quest ID
```

`CharCliChallengeEnum` walks that array and returns the IDs. It does not walk
a static catalog. `CharCliChallengeGetData(id, out)` binary-searches the same
array and returns, from the matching record:

```text
record + 0x00  id
record + 0x04  flags
record + 0x08  name wchar buffer
record + 0x0c  short description wchar buffer
```

`CharCliOnChallengeList` and `CharCliOnChallengeAdd` allocate and insert these
records from server-provided wide strings. This proves that the readable name
and initial description arrive through the runtime character data path; they
are not reconstructed from `gw.dat` by `CharCliChallengeGetData`.

`CharCliChallengeGetDescription` reads the same live record. When the loaded
description flag is set, it exposes additional buffers at record offsets
`0x2c` and `0x30`, plus the mission-related fields at `0x10` and `0x14`.
`CharCliOnChallengeDesc(id, text_a, text_b)` fills those buffers and sets the
loaded flag, but only after finding an existing record.

`CharCliChallengeRequestDescription(id)` therefore is not a static lookup. It
binary-searches the live array and sends `CharMsgSendChallengeDesc(id)` when
the existing record needs its description. An ID absent from the array cannot
be completed by this path. This matches the current Reforged guard that first
requires `GetQuest(id)` to succeed.

### Confirmed network request/response path

The WASM request path is now mapped far enough to explain the boundary:

```text
CharCliChallengeRequestDescription(id)
  -> CharMsgSendChallengeDesc(id)
     -> outgoing 8-byte struct: { 0x12, challenge_id }

server challenge-description packet
  -> OnMsgSrvChallengeDesc(packet)
     -> id at packet + 0x04
     -> UTF-16 text A at packet + 0x08
     -> UTF-16 text B at packet + 0x108
     -> CharCliOnChallengeDesc(id, text_a, text_b)
```

The response handler does not create a missing cache record. It calls
`CharCliOnChallengeDesc`, which searches the existing `ChallengeDisplay`
array and updates the matching record. Sending the 0x12 request directly for
an arbitrary ID would therefore not solve the missing-record problem.

The cache population packets are separate:

```text
OnMsgSrvChallengeListData(packet)
  id      at +0x04
  flags   at +0x08
  name    at +0x0c
  text    at +0x1c
  group   at +0x2c
  mission at +0x3c
  -> CharCliOnChallengeList(...)

OnMsgSrvChallengeAdd(packet)
  -> CharCliOnChallengeAdd(...)
```

These server callbacks are the actual source of the complete currently
available quest/challenge entries. The related `OnMsgSrvQuestBlurb` and
`OnMsgSrvQuestGoalAdd` handlers populate the separate blurb and goal caches.
No `OnMsgSrvQuestInfo`/static-catalog getter was found in the named WASM
surface; the old GWCA `RequestQuestInfo` pair is a different client-side
operation and remains gated by the runtime quest log in Reforged.

The same pattern exists for ordinary quest-support data:

```text
CharClient + 0x564  -> GoalDisplay array pointer
CharClient + 0x568  -> capacity
CharClient + 0x56c  -> count
GoalDisplay         -> 0x0c-byte records
```

`CharCliGoalEnum`/`CharCliGoalGetData` enumerate that live goal cache, while
`CharCliOnQuestGoalAdd` receives and stores goal text. Quest blurbs use another
runtime array at `+0x4f8` with count at `+0x500`. The quest UI consumes these
enumerators and the challenge cache; it does not reveal a complete offline
quest catalog.

### Consequence for dumping all quests

The WASM evidence separates two possible dump targets:

1. A **runtime dump** is practical now: enumerate the live challenge/goal/
   blurb caches, copy their wide strings, and expose one native snapshot to
   Python. This can dump all quests currently delivered to the character,
   including names, descriptions, and goals, without changing the active
   quest.
2. A **complete offline catalog** is not provided by these caches. `gw.dat`
   may contain localized resources, but these functions do not provide the
   catalog mapping from every quest ID to those resources. A separate static
   table or the server protocol would have to be located before a full game-
   wide dump is possible.

The safest next implementation is therefore a native, game-thread snapshot
API over the existing live arrays. It should copy strings while on the game
thread and return immutable records to Python. It should not request arbitrary
IDs or mutate the active quest. A Ghidra exporter can still be useful for
verifying the layouts and resolving the x86 addresses, but it cannot produce a
complete game-wide quest dump from these runtime arrays alone.

### What can be dumped safely from Python today

For quests already present in the character's quest log, Python already has
enough access to produce a names/descriptions dump without selecting a quest:

```text
GLOBAL_CACHE.Quest.GetQuestLogIds()
  -> RequestQuestName / RequestQuestDescription
  -> IsQuest*Ready
  -> GetQuestName / GetQuestDescription
```

The native binding resolves the encoded string pointers on the game thread and
returns ordinary Python strings. This is a runtime dump of the current log, not
a database export. It should run as a serialized request job (one quest and one
field at a time), or be replaced by a native snapshot API, rather than polling
all fields concurrently from a UI callback.

The current `PyQuest.get_quest_data()`/`GetQuestData()` result is deliberately
only the context metadata record; its string members are not filled by that
getter. The async `RequestQuest*`/`GetQuest*` methods are the existing text
decoder path. This is why a direct metadata dump can contain IDs and map data
while names and descriptions remain empty.

For a broader runtime dump, the native implementation should expose a copied
snapshot of the live challenge, goal, and blurb arrays. The copy must happen on
the game thread and the returned records must own their strings. Python can then
render or inspect the snapshot without touching Guild Wars-owned pointers or
issuing requests.

### Why a Ghidra script is not the right exporter

An ordinary Ghidra script can recover layouts, packet offsets, and x86
addresses, but it analyzes the executable image; it does not have the current
character's populated server-side quest records. A debugger-attached Ghidra
script could inspect one live client, but it would still read the same runtime
arrays and would not discover quests that the server has not sent to that
client. Ghidra is useful for validating the native snapshot implementation,
not for generating a complete quest catalog.

## Current Party Quest Log behavior

The loader now requests each quest by ID without changing the player's active
quest. The sequence is:

```text
read quest-log IDs
→ request quest info for that ID
→ read cached metadata
→ request/decode text fields by ID
→ poll ready flags
```

It no longer requires the primary quest to be fetched first, and it no longer
sets/restores the active quest for every node. Mission-map quest ID `-1` skips
the normal quest-info request because its data comes from mission-objective
context instead.

## Remaining limitation

Text acquisition is still serialized and polling-based. The proper long-term
native design is a game-thread quest-request queue plus a native decoded
snapshot/cache, exposed to Python as one ready snapshot per quest. That would
remove the per-field polling and make the Party Quest Log a read-only consumer
of stable data.
