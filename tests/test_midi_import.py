#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This module contains tests for importing MIDI files.
"""

import os
import logging
import warnings
from collections import defaultdict, Counter
from operator import itemgetter
import unittest
from tempfile import NamedTemporaryFile
import mido

from partitura import load_score_midi
from partitura.utils import partition
import partitura.score as score
from partitura import load_performance_midi
from tests import MIDIINPORT_TESTFILES

LOGGER = logging.getLogger(__name__)


def fill_track(track, notes, divs, vel=64):
    # add on/off events for note specification (`notes`) to `track`
    onoffs = defaultdict(list)
    for on, off, pitch, ch in notes:
        on = int(divs * on)
        off = int(divs * off)
        onoffs[on].append(("note_on", pitch, ch))
        onoffs[off].append(("note_off", pitch, ch))

    times = sorted(onoffs.keys())
    prev = 0
    for t in times:
        dt = t - prev
        for msg, pitch, ch in onoffs[t]:
            track.append(
                mido.Message(msg, note=pitch, velocity=vel, channel=ch, time=dt)
            )
            dt = 0
        prev = t


def make_assignment_mode_example():
    # create a midi file on which to test the assignment modes in load_score_midi
    divs = 10
    mid = mido.MidiFile(ticks_per_beat=divs)
    track_1 = mido.MidiTrack()
    mid.tracks.append(track_1)
    tempo = int(0.5 * 10**6)
    track_1.append(mido.MetaMessage("track_name", name="Track 1"))
    # track_1.append(mido.MetaMessage('instrument_name', name='Instrument 1'))
    # track_1.append(mido.Message('program_change', channel=0, program=1))
    # track_1.append(mido.MetaMessage('set_tempo', tempo=tempo))
    track_1.append(
        mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0)
    )

    track_2 = mido.MidiTrack()
    mid.tracks.append(track_2)
    track_2.append(mido.MetaMessage("track_name", name="Track 2"))
    # track_2.append(mido.MetaMessage('instrument_name', name='Instrument 2'))
    # track_2.append(mido.Message('program_change', channel=1, program=57))
    # track_2.append(mido.MetaMessage('set_tempo', tempo=tempo))
    track_2.append(
        mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0)
    )

    # on off pitch ch, (times in quarter)
    notes_1 = [
        (0, 1, 76, 0),
        (1, 2, 76, 0),
        (2, 3, 76, 0),
        (0, 4, 69, 2),
    ]
    notes_2 = [
        (0, 2, 80, 1),
        (2, 4, 69, 1),
    ]

    fill_track(track_1, notes_1, divs)
    fill_track(track_2, notes_2, divs)
    return mid


def get_track_voice_numbers(mid):
    tc_counter = Counter()
    for i, track in enumerate(mid.tracks):
        for msg in track:
            if msg.type == "note_on":
                tc_counter.update(((i, msg.channel),))
    return tc_counter


def make_triplets_example_1():
    divs = 120
    mid = mido.MidiFile(ticks_per_beat=divs)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))

    # define two consecutive quarter triplets
    # on off pitch ch, (times in quarter)
    notes = [
        (0, 2 / 3, 76, 0),
        (2 / 3, 4 / 3, 76, 0),
        (4 / 3, 2, 76, 0),
        (2, 8 / 3, 76, 0),
        (8 / 3, 10 / 3, 76, 0),
        (10 / 3, 4, 76, 0),
    ]
    fill_track(track, notes, divs)
    # target:
    actual_notes = [3] * 6
    normal_notes = [2] * 6
    return mid, actual_notes, normal_notes


def make_triplets_example_2():
    divs = 120
    mid = mido.MidiFile(ticks_per_beat=divs)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))

    # define two consecutive quarter triplets
    # on off pitch ch, (times in quarter)
    notes = [
        (0, 2 / 5, 76, 0),
        (2 / 5, 4 / 5, 76, 0),
        (4 / 5, 6 / 5, 76, 0),
        (6 / 5, 8 / 5, 76, 0),
        (8 / 5, 2, 76, 0),
        (2, 8 / 3, 76, 0),
        (8 / 3, 10 / 3, 76, 0),
        (10 / 3, 4, 76, 0),
    ]
    fill_track(track, notes, divs)
    # target:
    actual_notes = [5] * 5 + [3] * 3
    normal_notes = [4] * 5 + [2] * 3
    return mid, actual_notes, normal_notes


class TestLoadScoreMIDIFiles(unittest.TestCase):
    """
    Test load_score_midi with various MIDI files.  The MIDI files are special in
    that they have multiple instances of the same event type (key sig, time sig,
    tempo, respectively) occurring at the same time point.
    """

    def _create_key_signature_test_file(self):
        """Create a MIDI file with multiple key changes at the same time."""
        key_mid = mido.MidiFile()
        track = mido.MidiTrack()
        key_mid.tracks.append(track)
        self.keys = ["C", "G"]
        track.append(mido.MetaMessage("key_signature", key=self.keys[0], time=0))
        track.append(
            mido.MetaMessage("key_signature", key=self.keys[1], time=0)
        )  # Same time
        track.append(mido.Message("note_on", note=60, velocity=64, time=480))
        track.append(mido.Message("note_off", note=60, velocity=64, time=480))
        key_file = NamedTemporaryFile(suffix="_key.mid", delete=False).name
        key_mid.save(key_file)
        return key_file

    def _create_time_signature_test_file(self):
        """Create a MIDI file with multiple time signature changes at the same time."""
        time_mid = mido.MidiFile()
        track = mido.MidiTrack()
        time_mid.tracks.append(track)
        self.time_sigs = [(4, 4), (3, 4)]
        for num, den in self.time_sigs:
            track.append(
                mido.MetaMessage(
                    "time_signature", numerator=num, denominator=den, time=0
                )
            )
        track.append(mido.Message("note_on", note=60, velocity=64, time=480))
        track.append(mido.Message("note_off", note=60, velocity=64, time=480))
        time_file = NamedTemporaryFile(suffix="_time.mid", delete=False).name
        time_mid.save(time_file)
        return time_file

    def _create_tempo_test_file(self):
        """Create a MIDI file with multiple tempo changes at the same time."""
        tempo_mid = mido.MidiFile()
        track = mido.MidiTrack()
        tempo_mid.tracks.append(track)
        self.tempos = [120, 60]  # Store tempos as an instance attribute
        track.append(
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(self.tempos[0]), time=0)
        )
        track.append(
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(self.tempos[1]), time=0)
        )  # Same time
        track.append(mido.Message("note_on", note=60, velocity=64, time=480))
        track.append(mido.Message("note_off", note=60, velocity=64, time=480))
        tempo_file = NamedTemporaryFile(suffix="_tempo.mid", delete=False).name
        tempo_mid.save(tempo_file)
        return tempo_file

    def setUp(self):
        """Create temporary MIDI files for testing multiple event types."""
        # Create temporary MIDI files for testing
        self.test_files = {
            "key": self._create_key_signature_test_file(),
            "time": self._create_time_signature_test_file(),
            "tempo": self._create_tempo_test_file(),
        }
        self.temp_files = self.test_files.copy()  # For cleanup

    def test_load_multiple_files(self):
        """Test loading multiple MIDI files using specific test methods"""
        for key in self.test_files.keys():
            # Dynamically call the test method for each file type
            test_method = getattr(self, f"_test_{key}", None)
            if test_method:
                test_method()
            else:
                self.fail(f"No test method found for {key} file type")

    def _test_key(self):
        """Test key signature MIDI file"""
        try:
            song = load_score_midi(self.test_files["key"])
            self.assertIsNotNone(song)
            self.assertTrue(len(song.parts) > 0)
            part = song.parts[0]
            keys = [ks.name for ks in part.iter_all(score.KeySignature)]
            assert keys == self.keys
        except Exception as e:
            self.fail(f"Failed to load key signature test file: {str(e)}")

    def _test_time(self):
        """Test time signature MIDI file"""
        try:
            song = load_score_midi(self.test_files["time"])
            self.assertIsNotNone(song)
            self.assertTrue(len(song.parts) > 0)
            part = song.parts[0]
            time_sigs = [
                (ts.beats, ts.beat_type) for ts in part.iter_all(score.TimeSignature)
            ]
            assert time_sigs == self.time_sigs

        except Exception as e:
            self.fail(f"Failed to load time signature test file: {str(e)}")

    def _test_tempo(self):
        """Test tempo MIDI file"""
        try:
            song = load_score_midi(self.test_files["tempo"])
            self.assertIsNotNone(song)
            self.assertTrue(len(song.parts) > 0)

            # Extract tempo values from the first part
            part = song.parts[0]

            # Collect tempo markings
            tempos = [tempo.bpm for tempo in part.iter_all(score.Tempo)]

            # Assert that the collected tempos match the original input
            assert tempos == self.tempos

        except Exception as e:
            self.fail(f"Failed to load tempo test file: {str(e)}")

    def tearDown(self):
        # Clean up temporary files
        for f in self.temp_files.values():
            try:
                os.unlink(f)
            except:
                pass


class TestMIDITuplets(unittest.TestCase):
    example_gen_funcs = (make_triplets_example_1, make_triplets_example_2)

    def test_tuplets(self):
        for example_gen_func in self.example_gen_funcs:
            mid, actual, normal = example_gen_func()
            with NamedTemporaryFile(suffix=".mid", delete=False) as fh:
                mid.save(fh.name)
                scr = load_score_midi(fh.name, part_voice_assign_mode=0)
                part = scr[0]
                notes = part.notes

                if len(actual) != len(normal):
                    LOGGER.warning("Error in example case, skipping test")
                    return
                msg = "Example Part has an unexpected number of notes (expected {}, got {})".format(
                    len(actual), len(notes)
                )
                self.assertEqual(len(notes), len(actual), msg)
                sym_durs = [n.symbolic_duration for n in notes]
                msg = "Incorrectly detected tuplets"
                self.assertEqual(
                    actual, [sd.get("actual_notes") for sd in sym_durs], msg
                )
                self.assertEqual(
                    normal, [sd.get("normal_notes") for sd in sym_durs], msg
                )


class TestMIDIImportModes(unittest.TestCase):
    def setUp(self):
        self.mid = make_assignment_mode_example()
        self.notes_per_tr_ch = get_track_voice_numbers(self.mid)
        self.tmpfile = NamedTemporaryFile(suffix=".mid", delete=False)
        self.mid.save(self.tmpfile.name)

    def test_midi_import_mode_0(self):
        parts = load_score_midi(self.tmpfile.name, part_voice_assign_mode=0)
        by_track = partition(itemgetter(0), self.notes_per_tr_ch.keys())

        msg = (
            "Number of parts {} does not equal number of tracks {} while "
            "testing part_voice_assign_mode=0 in load_score_midi"
        ).format(len(parts), len(by_track))
        self.assertEqual(len(parts), len(by_track), msg)

        for part, tr in zip(parts, by_track):

            msg = "{} should be a Part instance but it is not".format(part)
            self.assertTrue(isinstance(part, score.Part), msg)

            n_track_notes = sum(self.notes_per_tr_ch[tr_ch] for tr_ch in by_track[tr])
            part_notes = part.notes
            n_part_notes = len(part_notes)
            msg = "Part should have {} notes but it has".format(
                n_track_notes, n_part_notes
            )
            self.assertEqual(n_track_notes, n_part_notes, msg)

            n_ch_notes = [self.notes_per_tr_ch[tr_ch] for tr_ch in by_track[tr]]
            n_voice_notes = [
                len(vn)
                for v, vn in partition(
                    lambda x: x, [n.voice for n in part_notes]
                ).items()
            ]
            msg = "Part voices should have {} notes respectively, but they have {}".format(
                n_ch_notes, n_voice_notes
            )
            self.assertEqual(n_ch_notes, n_voice_notes, msg)

    def test_midi_import_mode_1(self):
        scr = load_score_midi(self.tmpfile.name, part_voice_assign_mode=1)

        parts = scr.part_structure
        by_track = partition(itemgetter(0), self.notes_per_tr_ch.keys())
        msg = (
            "Number of partgroups {} does not equal number of tracks {} while "
            "testing part_voice_assign_mode=0 in load_score_midi"
        ).format(len(parts), len(by_track))
        self.assertEqual(len(parts), len(by_track), msg)

        for part_group, tr in zip(parts, by_track):

            msg = "{} should be a PartGroup instance but it is not"
            self.assertTrue(isinstance(part_group, score.PartGroup), msg)
            n_parts = len(part_group.children)
            n_channels = len(by_track[tr])
            msg = (
                "PartGroup should have as many parts as there are "
                "channels in the corresponding track {}, but it has {}".format(
                    n_channels, n_parts
                )
            )
            self.assertEqual(n_parts, n_channels, msg)

            for part, tr_ch in zip(part_group.children, by_track[tr]):
                notes_in_track = self.notes_per_tr_ch[tr_ch]
                notes_in_part = len(part.notes)
                msg = "Part should have {} notes but it has {}".format(
                    notes_in_track, notes_in_part
                )
                self.assertEqual(notes_in_part, notes_in_track)

    def test_midi_import_mode_2(self):
        scr = load_score_midi(self.tmpfile.name, part_voice_assign_mode=2)
        self.assertTrue(len(scr) == 1)
        part = scr.part_structure[0]
        msg = "{} should be a Part instance but it is not".format(part)
        self.assertTrue(isinstance(part, score.Part), msg)
        by_track = partition(itemgetter(0), self.notes_per_tr_ch.keys())
        by_voice = partition(lambda x: x.voice, part.notes)
        n_track_notes = [
            sum(self.notes_per_tr_ch[tr_ch] for tr_ch in tr_chs)
            for tr_chs in by_track.values()
        ]
        n_voice_notes = [len(notes) for notes in by_voice.values()]
        msg = (
            "Number of notes per voice {} does not match number of "
            "notes per track {}".format(n_voice_notes, n_track_notes)
        )
        self.assertEqual(n_voice_notes, n_track_notes, msg)

    def test_midi_import_mode_3(self):
        parts = load_score_midi(self.tmpfile.name, part_voice_assign_mode=3)
        by_track = partition(itemgetter(0), self.notes_per_tr_ch.keys())

        msg = "Number of parts {} does not equal number of tracks {}".format(
            len(parts), len(by_track)
        )
        self.assertEqual(len(parts), len(by_track), msg)

        for part, tr in zip(parts, by_track):

            msg = "{} should be a Part instance but it is not".format(part)
            self.assertTrue(isinstance(part, score.Part), msg)

            n_track_notes = sum(self.notes_per_tr_ch[tr_ch] for tr_ch in by_track[tr])
            part_notes = part.notes
            n_part_notes = len(part_notes)
            msg = "Part should have {} notes but it has".format(
                n_track_notes, n_part_notes
            )
            self.assertEqual(n_track_notes, n_part_notes, msg)

    def test_midi_import_mode_4(self):
        scr = load_score_midi(self.tmpfile.name, part_voice_assign_mode=4)
        # this shold be a part
        part = scr.part_structure[0]
        msg = "{} should be a Part instance but it is not".format(part)
        self.assertTrue(isinstance(part, score.Part), msg)
        midi_notes = sum(self.notes_per_tr_ch.values())
        part_notes = len(part.notes)
        msg = "Part should have {} notes but it has".format(midi_notes, part_notes)
        self.assertEqual(midi_notes, part_notes, msg)

    def test_midi_import_mode_5(self):
        parts = load_score_midi(self.tmpfile.name, part_voice_assign_mode=5)
        msg = "Number of parts should be {} but it is {}".format(
            len(self.notes_per_tr_ch), len(parts)
        )
        self.assertEqual(len(parts), len(self.notes_per_tr_ch), msg)
        for part, trch_notes in zip(parts, self.notes_per_tr_ch.values()):
            part_notes = len(part.notes)
            msg = "Part should have {} notes but it has".format(trch_notes, part_notes)
            self.assertEqual(part_notes, trch_notes, msg)

    def tearDown(self):
        # remove tmp file
        self.tmpfile = None

class TestScoreMidi(unittest.TestCase):
    def test_time_signature(self):
        score = load_score_midi(MIDIINPORT_TESTFILES[0])
        self.assertEqual(score.note_array()["onset_beat"][2], 0.5)
        na = score.note_array(include_time_signature=True)
        self.assertTrue(all([n==3 for n in na["ts_beats"]]))
        self.assertTrue(all([d==8 for d in na["ts_beat_type"]]))
        
class TestLoadPerformanceMIDI(unittest.TestCase):
    def setUp(self):
        # create test MIDI file with tempo changes, time signatures, and key signatures
        self.midi_file = mido.MidiFile()
        track = mido.MidiTrack()
        self.midi_file.tracks.append(track)

        # set initial tempo (120 BPM)
        track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120), time=0))
        # set initial time signature (4/4)
        track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
        # set initial key signature (C major)
        track.append(mido.MetaMessage('key_signature', key='C', time=0))
        # add note
        track.append(mido.Message('note_on', note=60, velocity=64, time=0))
        track.append(mido.Message('note_off', note=60, velocity=64, time=480))
        # change tempo to 60 BPM
        track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(60), time=0))
        # change time signature to 3/4
        track.append(mido.MetaMessage('time_signature', numerator=3, denominator=4, time=0))
        # change key signature to G major
        track.append(mido.MetaMessage('key_signature', key='G', time=0))
        # add another note
        track.append(mido.Message('note_on', note=62, velocity=64, time=0))
        track.append(mido.Message('note_off', note=62, velocity=64, time=480))

    def test_adjust_time(self):
        
        performance = load_performance_midi(self.midi_file)

        notes = performance.performedparts[0].notes
        self.assertAlmostEqual(notes[0]['note_on'], 0.0, places=6)
        self.assertAlmostEqual(notes[0]['note_off'], 0.5, places=6)  # 120 BPM -> 0.5 seconds
        self.assertAlmostEqual(notes[1]['note_on'], 0.5, places=6)
        self.assertAlmostEqual(notes[1]['note_off'], 1.5, places=6)  # 60 BPM -> 1 second

    def test_time_signature_and_key_signature(self):
        
        performance = load_performance_midi(self.midi_file).performedparts[0]

        time_signatures = performance.time_signatures
        key_signatures = performance.key_signatures

        self.assertEqual(time_signatures[0]['beats'], 4)
        self.assertEqual(time_signatures[0]['beat_type'], 4)
        self.assertAlmostEqual(time_signatures[0]['time'], 0.0, places=6)

        self.assertEqual(time_signatures[1]['beats'], 3)
        self.assertEqual(time_signatures[1]['beat_type'], 4)
        self.assertAlmostEqual(time_signatures[1]['time'], 0.5, places=6)  # 120 BPM -> 0.5 seconds

        self.assertEqual(key_signatures[0]['key_name'], 'C')
        self.assertAlmostEqual(key_signatures[0]['time'], 0.0, places=6)

        self.assertEqual(key_signatures[1]['key_name'], 'G')
        self.assertAlmostEqual(key_signatures[1]['time'], 0.5, places=6)  # 120 BPM -> 0.5 seconds


# ---------------------------------------------------------------------------
# Helpers for fixed-MIDI event pairing tests
# ---------------------------------------------------------------------------

PPQ = 480


def _save_temp_midi(mid):
    """Save an in-memory MidiFile to a temporary path and return the path."""
    f = NamedTemporaryFile(suffix=".mid", delete=False)
    mid.save(f.name)
    f.close()
    return f.name


def _make_retrigger_midi():
    """Same pitch retriggered before the first note is released."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    # note on at tick 0, retrigger at tick 240, note off at tick 480
    track.append(mido.Message("note_on", note=60, velocity=64, time=0))
    track.append(mido.Message("note_on", note=60, velocity=80, time=240))
    track.append(mido.Message("note_off", note=60, velocity=0, time=240))
    return mid


def _make_hanging_note_midi():
    """Note on events without any note off."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.Message("note_on", note=64, velocity=70, time=0))
    track.append(mido.Message("note_on", note=64, velocity=71, time=480))
    return mid


def _make_noteless_midi():
    """A MIDI file containing only meta events but no notes."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    return mid


def _make_tempo_on_second_track_midi():
    """Tempo map lives on a dedicated conductor track (the second track)."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    note_track = mido.MidiTrack()
    conductor_track = mido.MidiTrack()
    mid.tracks.append(note_track)
    mid.tracks.append(conductor_track)

    # two consecutive quarter notes
    note_track.append(mido.Message("note_on", note=60, velocity=64, time=0))
    note_track.append(mido.Message("note_off", note=60, velocity=0, time=PPQ))
    note_track.append(mido.Message("note_on", note=62, velocity=64, time=0))
    note_track.append(mido.Message("note_off", note=62, velocity=0, time=PPQ))

    # 120 bpm for the first beat, 60 bpm afterwards
    conductor_track.append(
        mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0)
    )
    conductor_track.append(
        mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=PPQ)
    )
    return mid


class TestMIDINoteEventPairing(unittest.TestCase):
    """Fixed-MIDI assertions for the shared on/off event pairing logic."""

    def test_retrigger_performance(self):
        """A retrigger closes the first note at the second note_on."""
        path = _save_temp_midi(_make_retrigger_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perf = load_performance_midi(path)
        finally:
            os.unlink(path)

        notes = perf.performedparts[0].notes
        # event count: two notes instead of one overwritten note
        self.assertEqual(len(notes), 2)
        self.assertEqual([n["midi_pitch"] for n in notes], [60, 60])
        self.assertEqual([n["velocity"] for n in notes], [64, 80])
        # pitches and seconds (120 bpm, 480 ppq -> 240 ticks = 0.25 s)
        self.assertAlmostEqual(notes[0]["note_on"], 0.0, places=6)
        self.assertAlmostEqual(notes[0]["note_off"], 0.25, places=6)
        self.assertAlmostEqual(notes[1]["note_on"], 0.25, places=6)
        self.assertAlmostEqual(notes[1]["note_off"], 0.5, places=6)
        # ticks are retained as well
        self.assertEqual(
            [(n["note_on_tick"], n["note_off_tick"]) for n in notes],
            [(0, 240), (240, 480)],
        )

    def test_retrigger_score(self):
        """load_score_midi uses the same pairing: two notes on retrigger."""
        path = _save_temp_midi(_make_retrigger_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                scr = load_score_midi(path)
        finally:
            os.unlink(path)

        na = scr.note_array()
        self.assertEqual(len(na), 2)
        self.assertEqual(list(na["pitch"]), [60, 60])
        self.assertEqual(
            [(int(n), int(d)) for n, d in zip(na["onset_div"], na["duration_div"])],
            [(0, 240), (240, 240)],
        )

    def test_hanging_note_performance(self):
        """Notes without a note_off are truncated to the last track event."""
        path = _save_temp_midi(_make_hanging_note_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perf = load_performance_midi(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(perf.performedparts), 1)
        notes = perf.performedparts[0].notes
        # the whole track must not be empty any more
        self.assertEqual(len(notes), 2)
        self.assertEqual([n["midi_pitch"] for n in notes], [64, 64])
        # both notes end at the last event tick (480 -> 0.5 s at 120 bpm)
        for n in notes:
            self.assertAlmostEqual(n["note_off"], 0.5, places=6)
            self.assertEqual(n["note_off_tick"], 480)
        self.assertAlmostEqual(notes[0]["note_on"], 0.0, places=6)
        self.assertAlmostEqual(notes[1]["note_on"], 0.5, places=6)

    def test_hanging_note_score(self):
        """load_score_midi keeps truncated hanging notes instead of crashing."""
        path = _save_temp_midi(_make_hanging_note_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                scr = load_score_midi(path)
        finally:
            os.unlink(path)
        # zero-duration truncated note becomes a grace note but is retained
        self.assertEqual(len(scr.note_array(include_grace_notes=True)), 2)

    def test_noteless_file_raises_value_error(self):
        """Files without any notes raise a ValueError, not an IndexError."""
        path = _save_temp_midi(_make_noteless_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with self.assertRaises(ValueError):
                    load_score_midi(path)
        finally:
            os.unlink(path)

    def test_noteless_file_performance(self):
        """The performance loader returns an empty performance, no crash."""
        path = _save_temp_midi(_make_noteless_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perf = load_performance_midi(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(perf.performedparts), 0)

    def test_tempo_on_second_track_seconds(self):
        """Tempo events outside the first track still drive second conversion."""
        path = _save_temp_midi(_make_tempo_on_second_track_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perf = load_performance_midi(path)
        finally:
            os.unlink(path)

        notes = sorted(perf.performedparts[0].notes, key=lambda n: n["midi_pitch"])
        by_pitch = {n["midi_pitch"]: n for n in notes}
        # first beat at 120 bpm = 0.5 s, second beat at 60 bpm = 1.0 s
        self.assertAlmostEqual(by_pitch[60]["note_on"], 0.0, places=6)
        self.assertAlmostEqual(by_pitch[60]["note_off"], 0.5, places=6)
        self.assertAlmostEqual(by_pitch[62]["note_on"], 0.5, places=6)
        self.assertAlmostEqual(by_pitch[62]["note_off"], 1.5, places=6)

    def test_tempo_on_second_track_score_tempos(self):
        """Score tempo objects are ordered along the global tick timeline."""
        path = _save_temp_midi(_make_tempo_on_second_track_midi())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                scr = load_score_midi(path)
        finally:
            os.unlink(path)

        part = scr.parts[0]
        tempos = [(tp.start.t, tp.bpm) for tp in part.iter_all(score.Tempo)]
        self.assertEqual(tempos, [(0, 120.0), (PPQ, 60.0)])


class TestMIDIGlobalTempoTimeline(unittest.TestCase):
    def test_tempo_changes_spread_across_tracks(self):
        """Tempo events spread over several tracks apply on one timeline."""
        mid = mido.MidiFile(ticks_per_beat=PPQ)
        note_track, tempo_track_1, tempo_track_2 = (
            mido.MidiTrack(),
            mido.MidiTrack(),
            mido.MidiTrack(),
        )
        mid.tracks.extend([note_track, tempo_track_1, tempo_track_2])
        # one note spanning three beats
        note_track.append(mido.Message("note_on", note=60, velocity=64, time=0))
        note_track.append(mido.Message("note_off", note=60, velocity=0, time=3 * PPQ))
        # 120 bpm -> 60 bpm at beat 1 -> 30 bpm at beat 2
        tempo_track_1.append(
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0)
        )
        tempo_track_1.append(
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=PPQ)
        )
        tempo_track_2.append(
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(30), time=2 * PPQ)
        )
        path = _save_temp_midi(mid)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perf = load_performance_midi(path)
        finally:
            os.unlink(path)

        note = perf.performedparts[0].notes[0]
        # 0.5 s + 1.0 s + 2.0 s = 3.5 s
        self.assertAlmostEqual(note["note_on"], 0.0, places=6)
        self.assertAlmostEqual(note["note_off"], 3.5, places=6)

    def test_default_bpm_without_tempo_events(self):
        mid = mido.MidiFile(ticks_per_beat=PPQ)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.Message("note_on", note=60, velocity=64, time=0))
        track.append(mido.Message("note_off", note=60, velocity=0, time=PPQ))
        path = _save_temp_midi(mid)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perf = load_performance_midi(path, default_bpm=60)
        finally:
            os.unlink(path)
        # one beat at 60 bpm = 1.0 s
        self.assertAlmostEqual(
            perf.performedparts[0].notes[0]["note_off"], 1.0, places=6
        )
