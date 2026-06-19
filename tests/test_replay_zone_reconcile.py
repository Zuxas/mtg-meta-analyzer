"""Tests for analysis.replay_events.reconcile_zones (headless, no Qt).

Exercises the raw zone-reconciliation logic against synthetic MTGA
GameStateMessage dicts. The core bug: Diff messages list only changed zones,
so reconciliation must touch ONLY zones present in the message.
"""
from analysis.replay_events import reconcile_zones


# MTGA zoneIds (stable within a game): 28 shared battlefield, 31/35 hands,
# 33/37 graveyards, 40/41 libraries.
def _zone(ztype, zoneid, ids, owner=None):
    z = {"type": ztype, "zoneId": zoneid, "objectInstanceIds": list(ids)}
    if owner is not None:
        z["ownerSeatId"] = owner
    return z


def _gsm(*zones):
    return {"zones": list(zones)}


def _fresh_state():
    # (instance_to_zoneid, zoneid_to_name) accumulate across messages.
    return {}, {}


# Common enrichment maps; owners make controller resolve to you/opp.
GRPIDS = {}            # iid -> grpid (unknown for face-down lib cards)
OWNERS = {}            # iid -> seat
NAMES = {}             # grpid -> name
MY, OPP = 1, 2


def _reconcile(gsm, i2z, z2n):
    return reconcile_zones(
        gsm, instance_to_zoneid=i2z, zoneid_to_name=z2n,
        instance_to_grpid=GRPIDS, instance_to_owner=OWNERS,
        grpid_names=NAMES, my_seat=MY, opp_seat=OPP,
    )


def test_full_message_establishes_membership():
    i2z, z2n = _fresh_state()
    full = _gsm(
        _zone("ZoneType_Hand", 31, [1, 2, 3, 4, 5, 6, 7], owner=1),
        _zone("ZoneType_Library", 40, list(range(100, 153)), owner=1),  # 53 ids
    )
    diffs = _reconcile(full, i2z, z2n)
    # 7 hand + 53 library = 60 enters; all from None
    assert sum(1 for d in diffs if d["to"] == "hand") == 7
    assert sum(1 for d in diffs if d["to"] == "library") == 53
    assert all(d["from"] is None for d in diffs)


def test_diff_omitting_a_zone_does_not_evict_it():
    # Bug repro: after a Full establishes hand+library, a battlefield-only Diff
    # must NOT evict the hand/library instances.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1, 2, 3], owner=1),
        _zone("ZoneType_Library", 40, [100, 101, 102], owner=1),
    ), i2z, z2n)
    diffs = _reconcile(_gsm(
        _zone("ZoneType_Battlefield", 28, [99]),
    ), i2z, z2n)
    # only the battlefield enter; NO evictions of hand/library
    assert [d for d in diffs if d["to"] is None] == []
    assert any(d["to"] == "battlefield" and d["instance_id"] == 99 for d in diffs)
    # hand/library instances still tracked
    assert i2z[1] == 31 and i2z[100] == 40


def test_draw_reads_as_move_not_evict_then_readd():
    # Card 100 moves library(40) -> hand(31). Both zones present in the diff.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1], owner=1),
        _zone("ZoneType_Library", 40, [100, 101], owner=1),
    ), i2z, z2n)
    diffs = _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1, 100], owner=1),
        _zone("ZoneType_Library", 40, [101], owner=1),
    ), i2z, z2n)
    moves = [d for d in diffs if d["instance_id"] == 100]
    assert len(moves) == 1
    assert moves[0]["from"] == "library" and moves[0]["to"] == "hand"
    assert [d for d in diffs if d["to"] is None] == []  # no spurious eviction
    assert i2z[100] == 31


def test_eviction_when_present_zone_loses_instance_to_unlisted_zone():
    # Card leaves hand(31) and its destination zone is NOT in the message.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1, 2], owner=1)), i2z, z2n)
    diffs = _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1], owner=1)), i2z, z2n)
    ev = [d for d in diffs if d["to"] is None]
    assert len(ev) == 1 and ev[0]["instance_id"] == 2 and ev[0]["from"] == "hand"
    assert 2 not in i2z


def test_two_seats_same_zone_name_are_independent():
    # P1 hand (31) and P2 hand (35) share the name "hand" but distinct zoneIds.
    # A diff updating only P1's hand must not evict P2's hand.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1, 2], owner=1),
        _zone("ZoneType_Hand", 35, [8, 9], owner=2),
    ), i2z, z2n)
    diffs = _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1], owner=1)), i2z, z2n)
    ev = [d["instance_id"] for d in diffs if d["to"] is None]
    assert ev == [2]            # only P1's discard
    assert i2z[8] == 35 and i2z[9] == 35  # P2 hand untouched


def test_game2_full_resyncs_membership():
    # A later Full (game 2) re-lists the same zoneIds; stale game-1 instances in
    # those present zones get evicted, new ones enter.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1, 2, 3], owner=1)), i2z, z2n)
    diffs = _reconcile(_gsm(_zone("ZoneType_Hand", 31, [50, 51], owner=1)), i2z, z2n)
    evicted = sorted(d["instance_id"] for d in diffs if d["to"] is None)
    entered = sorted(d["instance_id"] for d in diffs if d["to"] == "hand")
    assert evicted == [1, 2, 3]
    assert entered == [50, 51]


def test_unmapped_zones_ignored():
    # Limbo/Stack/etc. are not battlefield/hand/library/graveyard/exile.
    i2z, z2n = _fresh_state()
    diffs = _reconcile(_gsm(_zone("ZoneType_Limbo", 99, [1, 2])), i2z, z2n)
    assert diffs == []
    assert i2z == {}
