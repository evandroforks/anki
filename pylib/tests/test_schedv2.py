# coding: utf-8

import copy
import time

from anki import hooks
from anki.consts import *
from anki.lang import without_unicode_isolation
from anki.utils import intTime
from tests.shared import getEmptyCol as getEmptyColOrig


def getEmptyCol():
    col = getEmptyColOrig()
    col.changeSchedulerVer(2)
    return col


def test_clock():
    col = getEmptyCol()
    if (col.sched.dayCutoff - intTime()) < 10 * 60:
        raise Exception("Unit tests will fail around the day rollover.")


def checkRevIvl(col, c, targetIvl):
    min, max = col.sched._fuzzIvlRange(targetIvl)
    return min <= c.ivl <= max


def test_basics():
    col = getEmptyCol()
    col.reset()
    assert not col.sched.getCard()


def test_new():
    col = getEmptyCol()
    col.reset()
    assert col.sched.newCount == 0
    # add a note
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)
    col.reset()
    assert col.sched.newCount == 1
    # fetch it
    c = col.sched.getCard()
    assert c
    assert c.queue == QUEUE_TYPE_NEW
    assert c.type == CARD_TYPE_NEW
    # if we answer it, it should become a learn card
    t = intTime()
    col.sched.answerCard(c, 1)
    assert c.queue == QUEUE_TYPE_LRN
    assert c.type == CARD_TYPE_LRN
    assert c.due >= t

    # disabled for now, as the learn fudging makes this randomly fail
    # # the default order should ensure siblings are not seen together, and
    # # should show all cards
    # m = col.models.current(); mm = col.models
    # t = mm.newTemplate("Reverse")
    # t['qfmt'] = "{{Back}}"
    # t['afmt'] = "{{Front}}"
    # mm.addTemplate(m, t)
    # mm.save(m)
    # note = col.newNote()
    # note['Front'] = u"2"; note['Back'] = u"2"
    # col.addNote(note)
    # note = col.newNote()
    # note['Front'] = u"3"; note['Back'] = u"3"
    # col.addNote(note)
    # col.reset()
    # qs = ("2", "3", "2", "3")
    # for n in range(4):
    #     c = col.sched.getCard()
    #     assert qs[n] in c.q()
    #     col.sched.answerCard(c, 2)


def test_newLimits():
    col = getEmptyCol()
    # add some notes
    deck2 = col.decks.id("Default::foo")
    for i in range(30):
        note = col.newNote()
        note["Front"] = str(i)
        if i > 4:
            note.model()["did"] = deck2
        col.addNote(note)
    # give the child deck a different configuration
    c2 = col.decks.add_config_returning_id("new conf")
    col.decks.setConf(col.decks.get(deck2), c2)
    col.reset()
    # both confs have defaulted to a limit of 20
    assert col.sched.newCount == 20
    # first card we get comes from parent
    c = col.sched.getCard()
    assert c.did == 1
    # limit the parent to 10 cards, meaning we get 10 in total
    conf1 = col.decks.confForDid(1)
    conf1["new"]["perDay"] = 10
    col.decks.save(conf1)
    col.reset()
    assert col.sched.newCount == 10
    # if we limit child to 4, we should get 9
    conf2 = col.decks.confForDid(deck2)
    conf2["new"]["perDay"] = 4
    col.decks.save(conf2)
    col.reset()
    assert col.sched.newCount == 9


def test_newBoxes():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    col.reset()
    c = col.sched.getCard()
    conf = col.sched._cardConf(c)
    conf["new"]["delays"] = [1, 2, 3, 4, 5]
    col.decks.save(conf)
    col.sched.answerCard(c, 2)
    # should handle gracefully
    conf["new"]["delays"] = [1]
    col.decks.save(conf)
    col.sched.answerCard(c, 2)


def test_learn():
    col = getEmptyCol()
    # add a note
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)
    # set as a learn card and rebuild queues
    col.db.execute("update cards set queue=0, type=0")
    col.reset()
    # sched.getCard should return it, since it's due in the past
    c = col.sched.getCard()
    assert c
    conf = col.sched._cardConf(c)
    conf["new"]["delays"] = [0.5, 3, 10]
    col.decks.save(conf)
    # fail it
    col.sched.answerCard(c, 1)
    # it should have three reps left to graduation
    assert c.left % 1000 == 3
    assert c.left // 1000 == 3
    # it should be due in 30 seconds
    t = round(c.due - time.time())
    assert t >= 25 and t <= 40
    # pass it once
    col.sched.answerCard(c, 3)
    # it should be due in 3 minutes
    dueIn = c.due - time.time()
    assert 178 <= dueIn <= 180 * 1.25
    assert c.left % 1000 == 2
    assert c.left // 1000 == 2
    # check log is accurate
    log = col.db.first("select * from revlog order by id desc")
    assert log[3] == 3
    assert log[4] == -180
    assert log[5] == -30
    # pass again
    col.sched.answerCard(c, 3)
    # it should be due in 10 minutes
    dueIn = c.due - time.time()
    assert 599 <= dueIn <= 600 * 1.25
    assert c.left % 1000 == 1
    assert c.left // 1000 == 1
    # the next pass should graduate the card
    assert c.queue == QUEUE_TYPE_LRN
    assert c.type == CARD_TYPE_LRN
    col.sched.answerCard(c, 3)
    assert c.queue == QUEUE_TYPE_REV
    assert c.type == CARD_TYPE_REV
    # should be due tomorrow, with an interval of 1
    assert c.due == col.sched.today + 1
    assert c.ivl == 1
    # or normal removal
    c.type = CARD_TYPE_NEW
    c.queue = QUEUE_TYPE_LRN
    col.sched.answerCard(c, 4)
    assert c.type == CARD_TYPE_REV
    assert c.queue == QUEUE_TYPE_REV
    assert checkRevIvl(col, c, 4)
    # revlog should have been updated each time
    assert col.db.scalar("select count() from revlog where type = 0") == 5


def test_relearn():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    c.ivl = 100
    c.due = col.sched.today
    c.queue = CARD_TYPE_REV
    c.type = QUEUE_TYPE_REV
    c.flush()

    # fail the card
    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    assert c.queue == QUEUE_TYPE_LRN
    assert c.type == CARD_TYPE_RELEARNING
    assert c.ivl == 1

    # immediately graduate it
    col.sched.answerCard(c, 4)
    assert c.queue == CARD_TYPE_REV and c.type == QUEUE_TYPE_REV
    assert c.ivl == 2
    assert c.due == col.sched.today + c.ivl


def test_relearn_no_steps():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    c.ivl = 100
    c.due = col.sched.today
    c.queue = CARD_TYPE_REV
    c.type = QUEUE_TYPE_REV
    c.flush()

    conf = col.decks.confForDid(1)
    conf["lapse"]["delays"] = []
    col.decks.save(conf)

    # fail the card
    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    assert c.queue == CARD_TYPE_REV and c.type == QUEUE_TYPE_REV


def test_learn_collapsed():
    col = getEmptyCol()
    # add 2 notes
    note = col.newNote()
    note["Front"] = "1"
    col.addNote(note)
    note = col.newNote()
    note["Front"] = "2"
    col.addNote(note)
    # set as a learn card and rebuild queues
    col.db.execute("update cards set queue=0, type=0")
    col.reset()
    # should get '1' first
    c = col.sched.getCard()
    assert c.q().endswith("1")
    # pass it so it's due in 10 minutes
    col.sched.answerCard(c, 3)
    # get the other card
    c = col.sched.getCard()
    assert c.q().endswith("2")
    # fail it so it's due in 1 minute
    col.sched.answerCard(c, 1)
    # we shouldn't get the same card again
    c = col.sched.getCard()
    assert not c.q().endswith("2")


def test_learn_day():
    col = getEmptyCol()
    # add a note
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    col.sched.reset()
    c = col.sched.getCard()
    conf = col.sched._cardConf(c)
    conf["new"]["delays"] = [1, 10, 1440, 2880]
    col.decks.save(conf)
    # pass it
    col.sched.answerCard(c, 3)
    # two reps to graduate, 1 more today
    assert c.left % 1000 == 3
    assert c.left // 1000 == 1
    assert col.sched.counts() == (0, 1, 0)
    c = col.sched.getCard()
    ni = col.sched.nextIvl
    assert ni(c, 3) == 86400
    # answering it will place it in queue 3
    col.sched.answerCard(c, 3)
    assert c.due == col.sched.today + 1
    assert c.queue == QUEUE_TYPE_DAY_LEARN_RELEARN
    assert not col.sched.getCard()
    # for testing, move it back a day
    c.due -= 1
    c.flush()
    col.reset()
    assert col.sched.counts() == (0, 1, 0)
    c = col.sched.getCard()
    # nextIvl should work
    assert ni(c, 3) == 86400 * 2
    # if we fail it, it should be back in the correct queue
    col.sched.answerCard(c, 1)
    assert c.queue == QUEUE_TYPE_LRN
    col.undo()
    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 3)
    # simulate the passing of another two days
    c.due -= 2
    c.flush()
    col.reset()
    # the last pass should graduate it into a review card
    assert ni(c, 3) == 86400
    col.sched.answerCard(c, 3)
    assert c.queue == CARD_TYPE_REV and c.type == QUEUE_TYPE_REV
    # if the lapse step is tomorrow, failing it should handle the counts
    # correctly
    c.due = 0
    c.flush()
    col.reset()
    assert col.sched.counts() == (0, 0, 1)
    conf = col.sched._cardConf(c)
    conf["lapse"]["delays"] = [1440]
    col.decks.save(conf)
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    assert c.queue == QUEUE_TYPE_DAY_LEARN_RELEARN
    assert col.sched.counts() == (0, 0, 0)


def test_reviews():
    col = getEmptyCol()
    # add a note
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)
    # set the card up as a review card, due 8 days ago
    c = note.cards()[0]
    c.type = CARD_TYPE_REV
    c.queue = QUEUE_TYPE_REV
    c.due = col.sched.today - 8
    c.factor = STARTING_FACTOR
    c.reps = 3
    c.lapses = 1
    c.ivl = 100
    c.startTimer()
    c.flush()
    # save it for later use as well
    cardcopy = copy.copy(c)
    # try with an ease of 2
    ##################################################
    c = copy.copy(cardcopy)
    c.flush()
    col.reset()
    col.sched.answerCard(c, 2)
    assert c.queue == QUEUE_TYPE_REV
    # the new interval should be (100) * 1.2 = 120
    assert checkRevIvl(col, c, 120)
    assert c.due == col.sched.today + c.ivl
    # factor should have been decremented
    assert c.factor == 2350
    # check counters
    assert c.lapses == 1
    assert c.reps == 4
    # ease 3
    ##################################################
    c = copy.copy(cardcopy)
    c.flush()
    col.sched.answerCard(c, 3)
    # the new interval should be (100 + 8/2) * 2.5 = 260
    assert checkRevIvl(col, c, 260)
    assert c.due == col.sched.today + c.ivl
    # factor should have been left alone
    assert c.factor == STARTING_FACTOR
    # ease 4
    ##################################################
    c = copy.copy(cardcopy)
    c.flush()
    col.sched.answerCard(c, 4)
    # the new interval should be (100 + 8) * 2.5 * 1.3 = 351
    assert checkRevIvl(col, c, 351)
    assert c.due == col.sched.today + c.ivl
    # factor should have been increased
    assert c.factor == 2650
    # leech handling
    ##################################################
    conf = col.decks.getConf(1)
    conf["lapse"]["leechAction"] = LEECH_SUSPEND
    col.decks.save(conf)
    c = copy.copy(cardcopy)
    c.lapses = 7
    c.flush()
    # setup hook
    hooked = []

    def onLeech(card):
        hooked.append(1)

    hooks.card_did_leech.append(onLeech)
    col.sched.answerCard(c, 1)
    assert hooked
    assert c.queue == QUEUE_TYPE_SUSPENDED
    c.load()
    assert c.queue == QUEUE_TYPE_SUSPENDED


def test_review_limits():
    col = getEmptyCol()

    parent = col.decks.get(col.decks.id("parent"))
    child = col.decks.get(col.decks.id("parent::child"))

    pconf = col.decks.get_config(col.decks.add_config_returning_id("parentConf"))
    cconf = col.decks.get_config(col.decks.add_config_returning_id("childConf"))

    pconf["rev"]["perDay"] = 5
    col.decks.update_config(pconf)
    col.decks.setConf(parent, pconf["id"])
    cconf["rev"]["perDay"] = 10
    col.decks.update_config(cconf)
    col.decks.setConf(child, cconf["id"])

    m = col.models.current()
    m["did"] = child["id"]
    col.models.save(m, updateReqs=False)

    # add some cards
    for i in range(20):
        note = col.newNote()
        note["Front"] = "one"
        note["Back"] = "two"
        col.addNote(note)

        # make them reviews
        c = note.cards()[0]
        c.queue = CARD_TYPE_REV
        c.type = QUEUE_TYPE_REV
        c.due = 0
        c.flush()

    tree = col.sched.deck_due_tree().children
    # (('parent', 1514457677462, 5, 0, 0, (('child', 1514457677463, 5, 0, 0, ()),)))
    assert tree[0].review_count == 5  # parent
    assert tree[0].children[0].review_count == 5  # child

    # .counts() should match
    col.decks.select(child["id"])
    col.sched.reset()
    assert col.sched.counts() == (0, 0, 5)

    # answering a card in the child should decrement parent count
    c = col.sched.getCard()
    col.sched.answerCard(c, 3)
    assert col.sched.counts() == (0, 0, 4)

    tree = col.sched.deck_due_tree().children
    assert tree[0].review_count == 4  # parent
    assert tree[0].children[0].review_count == 4  # child


def test_button_spacing():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    # 1 day ivl review card due now
    c = note.cards()[0]
    c.type = CARD_TYPE_REV
    c.queue = QUEUE_TYPE_REV
    c.due = col.sched.today
    c.reps = 1
    c.ivl = 1
    c.startTimer()
    c.flush()
    col.reset()
    ni = col.sched.nextIvlStr
    wo = without_unicode_isolation
    assert wo(ni(c, 2)) == "2d"
    assert wo(ni(c, 3)) == "3d"
    assert wo(ni(c, 4)) == "4d"

    # if hard factor is <= 1, then hard may not increase
    conf = col.decks.confForDid(1)
    conf["rev"]["hardFactor"] = 1
    col.decks.save(conf)
    assert wo(ni(c, 2)) == "1d"


def test_overdue_lapse():
    # disabled in commit 3069729776990980f34c25be66410e947e9d51a2
    return
    col = getEmptyCol()  # pylint: disable=unreachable
    # add a note
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    # simulate a review that was lapsed and is now due for its normal review
    c = note.cards()[0]
    c.type = CARD_TYPE_REV
    c.queue = QUEUE_TYPE_LRN
    c.due = -1
    c.odue = -1
    c.factor = STARTING_FACTOR
    c.left = 2002
    c.ivl = 0
    c.flush()
    # checkpoint
    col.save()
    col.sched.reset()
    assert col.sched.counts() == (0, 2, 0)
    c = col.sched.getCard()
    col.sched.answerCard(c, 3)
    # it should be due tomorrow
    assert c.due == col.sched.today + 1
    # revert to before
    col.rollback()
    # with the default settings, the overdue card should be removed from the
    # learning queue
    col.sched.reset()
    assert col.sched.counts() == (0, 0, 1)


def test_nextIvl():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)
    col.reset()
    conf = col.decks.confForDid(1)
    conf["new"]["delays"] = [0.5, 3, 10]
    conf["lapse"]["delays"] = [1, 5, 9]
    col.decks.save(conf)
    c = col.sched.getCard()
    # new cards
    ##################################################
    ni = col.sched.nextIvl
    assert ni(c, 1) == 30
    assert ni(c, 2) == (30 + 180) // 2
    assert ni(c, 3) == 180
    assert ni(c, 4) == 4 * 86400
    col.sched.answerCard(c, 1)
    # cards in learning
    ##################################################
    assert ni(c, 1) == 30
    assert ni(c, 2) == (30 + 180) // 2
    assert ni(c, 3) == 180
    assert ni(c, 4) == 4 * 86400
    col.sched.answerCard(c, 3)
    assert ni(c, 1) == 30
    assert ni(c, 2) == (180 + 600) // 2
    assert ni(c, 3) == 600
    assert ni(c, 4) == 4 * 86400
    col.sched.answerCard(c, 3)
    # normal graduation is tomorrow
    assert ni(c, 3) == 1 * 86400
    assert ni(c, 4) == 4 * 86400
    # lapsed cards
    ##################################################
    c.type = CARD_TYPE_REV
    c.ivl = 100
    c.factor = STARTING_FACTOR
    assert ni(c, 1) == 60
    assert ni(c, 3) == 100 * 86400
    assert ni(c, 4) == 101 * 86400
    # review cards
    ##################################################
    c.queue = QUEUE_TYPE_REV
    c.ivl = 100
    c.factor = STARTING_FACTOR
    # failing it should put it at 60s
    assert ni(c, 1) == 60
    # or 1 day if relearn is false
    conf["lapse"]["delays"] = []
    col.decks.save(conf)
    assert ni(c, 1) == 1 * 86400
    # (* 100 1.2 86400)10368000.0
    assert ni(c, 2) == 10368000
    # (* 100 2.5 86400)21600000.0
    assert ni(c, 3) == 21600000
    # (* 100 2.5 1.3 86400)28080000.0
    assert ni(c, 4) == 28080000
    assert without_unicode_isolation(col.sched.nextIvlStr(c, 4)) == "10.8mo"


def test_bury():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    note = col.newNote()
    note["Front"] = "two"
    col.addNote(note)
    c2 = note.cards()[0]
    # burying
    col.sched.buryCards([c.id], manual=True)  # pylint: disable=unexpected-keyword-arg
    c.load()
    assert c.queue == QUEUE_TYPE_MANUALLY_BURIED
    col.sched.buryCards([c2.id], manual=False)  # pylint: disable=unexpected-keyword-arg
    c2.load()
    assert c2.queue == QUEUE_TYPE_SIBLING_BURIED

    col.reset()
    assert not col.sched.getCard()

    col.sched.unburyCardsForDeck(  # pylint: disable=unexpected-keyword-arg
        type="manual"
    )
    c.load()
    assert c.queue == QUEUE_TYPE_NEW
    c2.load()
    assert c2.queue == QUEUE_TYPE_SIBLING_BURIED

    col.sched.unburyCardsForDeck(  # pylint: disable=unexpected-keyword-arg
        type="siblings"
    )
    c2.load()
    assert c2.queue == QUEUE_TYPE_NEW

    col.sched.buryCards([c.id, c2.id])
    col.sched.unburyCardsForDeck(type="all")  # pylint: disable=unexpected-keyword-arg

    col.reset()

    assert col.sched.counts() == (2, 0, 0)


def test_suspend():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    # suspending
    col.reset()
    assert col.sched.getCard()
    col.sched.suspendCards([c.id])
    col.reset()
    assert not col.sched.getCard()
    # unsuspending
    col.sched.unsuspendCards([c.id])
    col.reset()
    assert col.sched.getCard()
    # should cope with rev cards being relearnt
    c.due = 0
    c.ivl = 100
    c.type = CARD_TYPE_REV
    c.queue = QUEUE_TYPE_REV
    c.flush()
    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    assert c.due >= time.time()
    due = c.due
    assert c.queue == QUEUE_TYPE_LRN
    assert c.type == CARD_TYPE_RELEARNING
    col.sched.suspendCards([c.id])
    col.sched.unsuspendCards([c.id])
    c.load()
    assert c.queue == QUEUE_TYPE_LRN
    assert c.type == CARD_TYPE_RELEARNING
    assert c.due == due
    # should cope with cards in cram decks
    c.due = 1
    c.flush()
    col.decks.newDyn("tmp")
    col.sched.rebuildDyn()
    c.load()
    assert c.due != 1
    assert c.did != 1
    col.sched.suspendCards([c.id])
    c.load()
    assert c.due != 1
    assert c.did != 1
    assert c.odue == 1


def test_filt_reviewing_early_normal():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    c.ivl = 100
    c.queue = CARD_TYPE_REV
    c.type = QUEUE_TYPE_REV
    # due in 25 days, so it's been waiting 75 days
    c.due = col.sched.today + 25
    c.mod = 1
    c.factor = STARTING_FACTOR
    c.startTimer()
    c.flush()
    col.reset()
    assert col.sched.counts() == (0, 0, 0)
    # create a dynamic deck and refresh it
    did = col.decks.newDyn("Cram")
    col.sched.rebuildDyn(did)
    col.reset()
    # should appear as normal in the deck list
    assert sorted(col.sched.deck_due_tree().children)[0].review_count == 1
    # and should appear in the counts
    assert col.sched.counts() == (0, 0, 1)
    # grab it and check estimates
    c = col.sched.getCard()
    assert col.sched.answerButtons(c) == 4
    assert col.sched.nextIvl(c, 1) == 600
    assert col.sched.nextIvl(c, 2) == int(75 * 1.2) * 86400
    assert col.sched.nextIvl(c, 3) == int(75 * 2.5) * 86400
    assert col.sched.nextIvl(c, 4) == int(75 * 2.5 * 1.15) * 86400

    # answer 'good'
    col.sched.answerCard(c, 3)
    checkRevIvl(col, c, 90)
    assert c.due == col.sched.today + c.ivl
    assert not c.odue
    # should not be in learning
    assert c.queue == QUEUE_TYPE_REV
    # should be logged as a cram rep
    assert col.db.scalar("select type from revlog order by id desc limit 1") == 3

    # due in 75 days, so it's been waiting 25 days
    c.ivl = 100
    c.due = col.sched.today + 75
    c.flush()
    col.sched.rebuildDyn(did)
    col.reset()
    c = col.sched.getCard()

    assert col.sched.nextIvl(c, 2) == 60 * 86400
    assert col.sched.nextIvl(c, 3) == 100 * 86400
    assert col.sched.nextIvl(c, 4) == 114 * 86400


def test_filt_keep_lrn_state():
    col = getEmptyCol()

    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)

    # fail the card outside filtered deck
    c = col.sched.getCard()
    conf = col.sched._cardConf(c)
    conf["new"]["delays"] = [1, 10, 61]
    col.decks.save(conf)

    col.sched.answerCard(c, 1)

    assert c.type == CARD_TYPE_LRN and c.queue == QUEUE_TYPE_LRN
    assert c.left == 3003

    col.sched.answerCard(c, 3)
    assert c.type == CARD_TYPE_LRN and c.queue == QUEUE_TYPE_LRN

    # create a dynamic deck and refresh it
    did = col.decks.newDyn("Cram")
    col.sched.rebuildDyn(did)
    col.reset()

    # card should still be in learning state
    c.load()
    assert c.type == CARD_TYPE_LRN and c.queue == QUEUE_TYPE_LRN
    assert c.left == 2002

    # should be able to advance learning steps
    col.sched.answerCard(c, 3)
    # should be due at least an hour in the future
    assert c.due - intTime() > 60 * 60

    # emptying the deck preserves learning state
    col.sched.emptyDyn(did)
    c.load()
    assert c.type == CARD_TYPE_LRN and c.queue == QUEUE_TYPE_LRN
    assert c.left == 1001
    assert c.due - intTime() > 60 * 60


def test_preview():
    # add cards
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    orig = copy.copy(c)
    note2 = col.newNote()
    note2["Front"] = "two"
    col.addNote(note2)
    # cram deck
    did = col.decks.newDyn("Cram")
    cram = col.decks.get(did)
    cram["resched"] = False
    col.decks.save(cram)
    col.sched.rebuildDyn(did)
    col.reset()
    # grab the first card
    c = col.sched.getCard()
    assert col.sched.answerButtons(c) == 2
    assert col.sched.nextIvl(c, 1) == 600
    assert col.sched.nextIvl(c, 2) == 0
    # failing it will push its due time back
    due = c.due
    col.sched.answerCard(c, 1)
    assert c.due != due

    # the other card should come next
    c2 = col.sched.getCard()
    assert c2.id != c.id

    # passing it will remove it
    col.sched.answerCard(c2, 2)
    assert c2.queue == QUEUE_TYPE_NEW
    assert c2.reps == 0
    assert c2.type == CARD_TYPE_NEW

    # the other card should appear again
    c = col.sched.getCard()
    assert c.id == orig.id

    # emptying the filtered deck should restore card
    col.sched.emptyDyn(did)
    c.load()
    assert c.queue == QUEUE_TYPE_NEW
    assert c.reps == 0
    assert c.type == CARD_TYPE_NEW


def test_ordcycle():
    col = getEmptyCol()
    # add two more templates and set second active
    m = col.models.current()
    mm = col.models
    t = mm.newTemplate("Reverse")
    t["qfmt"] = "{{Back}}"
    t["afmt"] = "{{Front}}"
    mm.addTemplate(m, t)
    t = mm.newTemplate("f2")
    t["qfmt"] = "{{Front}}"
    t["afmt"] = "{{Back}}"
    mm.addTemplate(m, t)
    mm.save(m)
    # create a new note; it should have 3 cards
    note = col.newNote()
    note["Front"] = "1"
    note["Back"] = "1"
    col.addNote(note)
    assert col.cardCount() == 3
    col.reset()
    # ordinals should arrive in order
    assert col.sched.getCard().ord == 0
    assert col.sched.getCard().ord == 1
    assert col.sched.getCard().ord == 2


def test_counts_idx():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)
    col.reset()
    assert col.sched.counts() == (1, 0, 0)
    c = col.sched.getCard()
    # counter's been decremented but idx indicates 1
    assert col.sched.counts() == (0, 0, 0)
    assert col.sched.countIdx(c) == 0
    # answer to move to learn queue
    col.sched.answerCard(c, 1)
    assert col.sched.counts() == (0, 1, 0)
    # fetching again will decrement the count
    c = col.sched.getCard()
    assert col.sched.counts() == (0, 0, 0)
    assert col.sched.countIdx(c) == 1
    # answering should add it back again
    col.sched.answerCard(c, 1)
    assert col.sched.counts() == (0, 1, 0)


def test_repCounts():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    col.reset()
    # lrnReps should be accurate on pass/fail
    assert col.sched.counts() == (1, 0, 0)
    col.sched.answerCard(col.sched.getCard(), 1)
    assert col.sched.counts() == (0, 1, 0)
    col.sched.answerCard(col.sched.getCard(), 1)
    assert col.sched.counts() == (0, 1, 0)
    col.sched.answerCard(col.sched.getCard(), 3)
    assert col.sched.counts() == (0, 1, 0)
    col.sched.answerCard(col.sched.getCard(), 1)
    assert col.sched.counts() == (0, 1, 0)
    col.sched.answerCard(col.sched.getCard(), 3)
    assert col.sched.counts() == (0, 1, 0)
    col.sched.answerCard(col.sched.getCard(), 3)
    assert col.sched.counts() == (0, 0, 0)
    note = col.newNote()
    note["Front"] = "two"
    col.addNote(note)
    col.reset()
    # initial pass should be correct too
    col.sched.answerCard(col.sched.getCard(), 3)
    assert col.sched.counts() == (0, 1, 0)
    col.sched.answerCard(col.sched.getCard(), 1)
    assert col.sched.counts() == (0, 1, 0)
    col.sched.answerCard(col.sched.getCard(), 4)
    assert col.sched.counts() == (0, 0, 0)
    # immediate graduate should work
    note = col.newNote()
    note["Front"] = "three"
    col.addNote(note)
    col.reset()
    col.sched.answerCard(col.sched.getCard(), 4)
    assert col.sched.counts() == (0, 0, 0)
    # and failing a review should too
    note = col.newNote()
    note["Front"] = "three"
    col.addNote(note)
    c = note.cards()[0]
    c.type = CARD_TYPE_REV
    c.queue = QUEUE_TYPE_REV
    c.due = col.sched.today
    c.flush()
    col.reset()
    assert col.sched.counts() == (0, 0, 1)
    col.sched.answerCard(col.sched.getCard(), 1)
    assert col.sched.counts() == (0, 1, 0)


def test_timing():
    col = getEmptyCol()
    # add a few review cards, due today
    for i in range(5):
        note = col.newNote()
        note["Front"] = "num" + str(i)
        col.addNote(note)
        c = note.cards()[0]
        c.type = CARD_TYPE_REV
        c.queue = QUEUE_TYPE_REV
        c.due = 0
        c.flush()
    # fail the first one
    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    # the next card should be another review
    c2 = col.sched.getCard()
    assert c2.queue == QUEUE_TYPE_REV
    # if the failed card becomes due, it should show first
    c.due = intTime() - 1
    c.flush()
    col.reset()
    c = col.sched.getCard()
    assert c.queue == QUEUE_TYPE_LRN


def test_collapse():
    col = getEmptyCol()
    # add a note
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    col.reset()
    # test collapsing
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    c = col.sched.getCard()
    col.sched.answerCard(c, 4)
    assert not col.sched.getCard()


def test_deckDue():
    col = getEmptyCol()
    # add a note with default deck
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    # and one that's a child
    note = col.newNote()
    note["Front"] = "two"
    default1 = note.model()["did"] = col.decks.id("Default::1")
    col.addNote(note)
    # make it a review card
    c = note.cards()[0]
    c.queue = QUEUE_TYPE_REV
    c.due = 0
    c.flush()
    # add one more with a new deck
    note = col.newNote()
    note["Front"] = "two"
    note.model()["did"] = col.decks.id("foo::bar")
    col.addNote(note)
    # and one that's a sibling
    note = col.newNote()
    note["Front"] = "three"
    note.model()["did"] = col.decks.id("foo::baz")
    col.addNote(note)
    col.reset()
    assert len(col.decks.all_names_and_ids()) == 5
    tree = col.sched.deck_due_tree().children
    assert tree[0].name == "Default"
    # sum of child and parent
    assert tree[0].deck_id == 1
    assert tree[0].review_count == 1
    assert tree[0].new_count == 1
    # child count is just review
    child = tree[0].children[0]
    assert child.name == "1"
    assert child.deck_id == default1
    assert child.review_count == 1
    assert child.new_count == 0
    # code should not fail if a card has an invalid deck
    c.did = 12345
    c.flush()
    col.sched.deck_due_tree()


def test_deckTree():
    col = getEmptyCol()
    col.decks.id("new::b::c")
    col.decks.id("new2")
    # new should not appear twice in tree
    names = [x.name for x in col.sched.deck_due_tree().children]
    names.remove("new")
    assert "new" not in names


def test_deckFlow():
    col = getEmptyCol()
    # add a note with default deck
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    # and one that's a child
    note = col.newNote()
    note["Front"] = "two"
    note.model()["did"] = col.decks.id("Default::2")
    col.addNote(note)
    # and another that's higher up
    note = col.newNote()
    note["Front"] = "three"
    default1 = note.model()["did"] = col.decks.id("Default::1")
    col.addNote(note)
    # should get top level one first, then ::1, then ::2
    col.reset()
    assert col.sched.counts() == (3, 0, 0)
    for i in "one", "three", "two":
        c = col.sched.getCard()
        assert c.note()["Front"] == i
        col.sched.answerCard(c, 3)


def test_reorder():
    col = getEmptyCol()
    # add a note with default deck
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    note2 = col.newNote()
    note2["Front"] = "two"
    col.addNote(note2)
    assert note2.cards()[0].due == 2
    found = False
    # 50/50 chance of being reordered
    for i in range(20):
        col.sched.randomizeCards(1)
        if note.cards()[0].due != note.id:
            found = True
            break
    assert found
    col.sched.orderCards(1)
    assert note.cards()[0].due == 1
    # shifting
    note3 = col.newNote()
    note3["Front"] = "three"
    col.addNote(note3)
    note4 = col.newNote()
    note4["Front"] = "four"
    col.addNote(note4)
    assert note.cards()[0].due == 1
    assert note2.cards()[0].due == 2
    assert note3.cards()[0].due == 3
    assert note4.cards()[0].due == 4
    col.sched.sortCards([note3.cards()[0].id, note4.cards()[0].id], start=1, shift=True)
    assert note.cards()[0].due == 3
    assert note2.cards()[0].due == 4
    assert note3.cards()[0].due == 1
    assert note4.cards()[0].due == 2


def test_forget():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    c.queue = QUEUE_TYPE_REV
    c.type = CARD_TYPE_REV
    c.ivl = 100
    c.due = 0
    c.flush()
    col.reset()
    assert col.sched.counts() == (0, 0, 1)
    col.sched.forgetCards([c.id])
    col.reset()
    assert col.sched.counts() == (1, 0, 0)


def test_resched():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    col.sched.reschedCards([c.id], 0, 0)
    c.load()
    assert c.due == col.sched.today
    assert c.ivl == 1
    assert c.queue == QUEUE_TYPE_REV and c.type == CARD_TYPE_REV
    col.sched.reschedCards([c.id], 1, 1)
    c.load()
    assert c.due == col.sched.today + 1
    assert c.ivl == +1


def test_norelearn():
    col = getEmptyCol()
    # add a note
    note = col.newNote()
    note["Front"] = "one"
    col.addNote(note)
    c = note.cards()[0]
    c.type = CARD_TYPE_REV
    c.queue = QUEUE_TYPE_REV
    c.due = 0
    c.factor = STARTING_FACTOR
    c.reps = 3
    c.lapses = 1
    c.ivl = 100
    c.startTimer()
    c.flush()
    col.reset()
    col.sched.answerCard(c, 1)
    col.sched._cardConf(c)["lapse"]["delays"] = []
    col.sched.answerCard(c, 1)


def test_failmult():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)
    c = note.cards()[0]
    c.type = CARD_TYPE_REV
    c.queue = QUEUE_TYPE_REV
    c.ivl = 100
    c.due = col.sched.today - c.ivl
    c.factor = STARTING_FACTOR
    c.reps = 3
    c.lapses = 1
    c.startTimer()
    c.flush()
    conf = col.sched._cardConf(c)
    conf["lapse"]["mult"] = 0.5
    col.decks.save(conf)
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    assert c.ivl == 50
    col.sched.answerCard(c, 1)
    assert c.ivl == 25


def test_moveVersions():
    col = getEmptyCol()
    col.changeSchedulerVer(1)

    n = col.newNote()
    n["Front"] = "one"
    col.addNote(n)

    # make it a learning card
    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)

    # the move to v2 should reset it to new
    col.changeSchedulerVer(2)
    c.load()
    assert c.queue == QUEUE_TYPE_NEW
    assert c.type == CARD_TYPE_NEW

    # fail it again, and manually bury it
    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    col.sched.buryCards([c.id])
    c.load()
    assert c.queue == QUEUE_TYPE_MANUALLY_BURIED

    # revert to version 1
    col.changeSchedulerVer(1)

    # card should have moved queues
    c.load()
    assert c.queue == QUEUE_TYPE_SIBLING_BURIED

    # and it should be new again when unburied
    col.sched.unburyCards()
    c.load()
    assert c.type == CARD_TYPE_NEW and c.queue == QUEUE_TYPE_NEW

    # make sure relearning cards transition correctly to v1
    col.changeSchedulerVer(2)
    # card with 100 day interval, answering again
    col.sched.reschedCards([c.id], 100, 100)
    c.load()
    c.due = 0
    c.flush()
    conf = col.sched._cardConf(c)
    conf["lapse"]["mult"] = 0.5
    col.decks.save(conf)
    col.sched.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 1)
    # due should be correctly set when removed from learning early
    col.changeSchedulerVer(1)
    c.load()
    assert c.due == 50


# cards with a due date earlier than the collection should retain
# their due date when removed
def test_negativeDueFilter():
    col = getEmptyCol()

    # card due prior to collection date
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)
    c = note.cards()[0]
    c.due = -5
    c.queue = QUEUE_TYPE_REV
    c.ivl = 5
    c.flush()

    # into and out of filtered deck
    did = col.decks.newDyn("Cram")
    col.sched.rebuildDyn(did)
    col.sched.emptyDyn(did)
    col.reset()

    c.load()
    assert c.due == -5


# hard on the first step should be the average of again and good,
# and it should be logged properly
def test_initial_repeat():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "one"
    note["Back"] = "two"
    col.addNote(note)

    col.reset()
    c = col.sched.getCard()
    col.sched.answerCard(c, 2)
    # should be due in ~ 5.5 mins
    expected = time.time() + 5.5 * 60
    assert expected - 10 < c.due < expected * 1.25

    ivl = col.db.scalar("select ivl from revlog")
    assert ivl == -5.5 * 60
