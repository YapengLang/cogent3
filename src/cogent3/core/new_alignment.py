from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from functools import singledispatch, singledispatchmethod
from typing import Iterator, Optional, Union

import numpy

from cogent3 import get_moltype
from cogent3.core.alphabet import CharAlphabet
from cogent3.core.location import IndelMap
from cogent3.core.moltype import MolType
from cogent3.core.sequence import (
    SliceRecordABC,
    _input_vals_neg_step,
    _input_vals_pos_step,
)
from cogent3.util.misc import get_object_provenance


SeqTypes = Union[str, bytes, numpy.ndarray]


@singledispatch
def seq_index(seq: SeqTypes, alphabet: CharAlphabet) -> numpy.ndarray:
    raise NotImplementedError(
        f"{seq_index.__name__} not implemented for type {type(seq)}"
    )


@seq_index.register
def _(seq: str, alphabet: CharAlphabet) -> numpy.ndarray:
    return alphabet.to_indices(seq)


@seq_index.register
def _(seq: bytes, alphabet: CharAlphabet) -> numpy.ndarray:
    return alphabet.to_indices(seq)


@seq_index.register
def _(seq: numpy.ndarray, alphabet: CharAlphabet) -> numpy.ndarray:
    return seq.astype(alphabet.array_type)


@singledispatch
def process_name_order(
    correct_names: Union[dict, tuple, list], name_order: tuple
) -> tuple:
    """dict (data) for constructor; tuple for SeqData instance"""
    raise NotImplementedError(
        f"process_name_order not implemented for type {type(correct_names)}"
    )


@process_name_order.register
def _(correct_names: dict, name_order: tuple) -> tuple:
    keys = correct_names.keys()
    if name_order is None:
        return tuple(keys)
    if set(name_order) == set(keys):
        return name_order
    raise ValueError("name_order does not match dictionary keys")


def _name_order_list_tuple(name_order, correct_names):
    """List and tuples have the same implementation for dispatch"""
    if name_order is None:
        return correct_names
    if set(name_order) <= set(correct_names):
        return tuple(name_order)
    raise ValueError("some names do not match")


@process_name_order.register
def _(correct_names: tuple, name_order: tuple) -> tuple:
    return _name_order_list_tuple(name_order, correct_names)


@process_name_order.register
def _(correct_names: list, name_order: tuple) -> tuple:
    return _name_order_list_tuple(name_order, correct_names)


class SeqDataView(SliceRecordABC):
    """
    A view class for SeqData, providing properties for different
    representations.

    self.seq is a SeqData() instance, but other properties are a reference to a single
    seqid only.

    Example
    -------
    data = {"seq1": "ACGT", "seq2": "GTTTGCA"}
    sd = SeqData(data=data)
    sdv = sd.get_seq_view(seqid="seq1")
    """

    __slots__ = ("seq", "start", "stop", "step", "_offset", "_seqid", "_seq_len")

    def __init__(
        self,
        *,
        seq: str,
        start: Optional[int] = None,
        stop: Optional[int] = None,
        step: Optional[int] = None,
        offset: int = 0,
        seqid: Optional[str] = None,
        seq_len: Optional[int] = None,
    ):
        if step == 0:
            raise ValueError("step cannot be 0")
        step = 1 if step is None else step

        self._seq_len = self._checked_seq_len(seq_len)
        func = _input_vals_pos_step if step > 0 else _input_vals_neg_step
        start, stop, step = func(self._seq_len, start, stop, step)
        self.seq = seq
        self.start = start
        self.stop = stop
        self.step = step
        self._offset = offset
        self._seqid = seqid

    def _checked_seq_len(self, seq_len) -> int:
        assert seq_len is not None
        return seq_len

    @property
    def _zero_slice(self):
        return self.__class__(seq=self.seq)

    @property
    def seqid(self) -> str:
        return self._seqid

    @property
    def seq_len(self) -> int:
        return self._seq_len

    def _get_init_kwargs(self):
        return {"seq": self.seq, "seqid": self.seqid}

    @property
    def str_value(self) -> str:
        raw = self.seq.get_seq_str(
            seqid=self.seqid, start=self.parent_start, stop=self.parent_stop
        )
        return raw if self.step == 1 else raw[:: self.step]

    @property
    def array_value(self) -> numpy.ndarray:
        raw = self.seq.get_seq_array(
            seqid=self.seqid, start=self.parent_start, stop=self.parent_stop
        )
        return raw if self.step == 1 else raw[:: self.step]

    @property
    def bytes_value(self) -> bytes:
        raw = self.seq.get_seq_bytes(
            seqid=self.seqid, start=self.parent_start, stop=self.parent_stop
        )
        return raw if self.step == 1 else raw[:: self.step]

    def __str__(self):
        return self.str_value

    def __array__(self):
        return self.array_value

    def __bytes__(self):
        return self.bytes_value

    def __len__(self):
        return abs((self.start - self.stop) // self.step)

    def __iter__(self):
        return iter(self.value)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        seq = f"{self.seq[:10]}...{self.seq[-5:]}" if self.seq_len > 15 else self.seq
        return (
            f"{self.__class__.__name__}(seq={seq!r}, start={self.start}, "
            f"stop={self.stop}, step={self.step}, offset={self.offset}, "
            f"seqid={self.seqid!r}, seq_len={self.seq_len})"
        )

    def to_rich_dict(self):
        # get the current state
        data = {"type": get_object_provenance(self), "version": __version__}
        data["init_args"] = self._get_init_kwargs()
        # since we will truncate the seq, we don't need start, stop,
        # step is sufficient
        data["init_args"]["step"] = self.step
        if self.is_reversed:
            adj = self.seq_len + 1
            start, stop = self.stop + adj, self.start + adj
        else:
            start, stop = self.start, self.stop

        data["init_args"]["seq"] = self.seq[start:stop]
        data["init_args"]["offset"] = int(self.parent_start)
        return data

    @classmethod
    def from_rich_dict(cls, data: dict):
        init_args = data.pop("init_args")
        if "offset" in data:
            init_args["offset"] = data.pop("offset")
        return cls(**init_args)

    def copy(self, sliced: bool = False):
        """returns copy

        Parameters
        ----------
        sliced
            if True, the underlying sequence is truncated and the start/stop
            adjusted
        """
        if not sliced:
            return self.__class__(
                seq=self.seq,
                start=self.start,
                stop=self.stop,
                step=self.step,
                offset=self.offset,
                seqid=self.seqid,
                seq_len=self.seq_len,
            )
        return self.from_rich_dict(self.to_rich_dict())


@dataclass
class SeqData:
    __slots__ = ("_data", "_alphabet", "_name_order", "_seq_maker")

    def __init__(
        self,
        data: dict[str, SeqTypes],
        alphabet: CharAlphabet,
        name_order: Optional[Union[tuple[str], None]] = None,
        seq_maker: Optional[type] = None,
    ):
        self._alphabet = alphabet
        self._name_order = process_name_order(data, name_order)
        self._seq_maker = seq_maker
        # Convert to moltype alphabet indicies
        self._data: dict[str, numpy.ndarray] = {
            k: seq_index(v, self._alphabet) for k, v in data.items()
        }

    @property
    def set_seq_maker(self) -> type:
        return self._seq_maker

    @set_seq_maker.setter
    def set_seq_maker(self, value: tuple[type, CharAlphabet]) -> type:
        seq_maker, alphabet = value
        if alphabet != self._alphabet:
            raise ValueError("Alphabets must be the same")
        assert alphabet == self._alphabet
        self._seq_maker = seq_maker

    def _make_seq(self, seqid) -> Union[SeqDataView, type]:
        seqdataview = self.get_seq_view(seqid=seqid)
        if self._seq_maker is None:
            return seqdataview
        return self.set_seq_maker(seqdataview, seqid=seqid)

    @singledispatchmethod
    def __getitem__(self, value: Union[str, int]) -> SeqDataView:
        raise NotImplementedError(f"__getitem__ not implemented for {type(value)}")

    @__getitem__.register
    def _(self, value: str) -> SeqDataView:
        return self._make_seq(seqid=value)

    @__getitem__.register
    def _(self, value: int) -> SeqDataView:
        seqid = self._name_order[value]
        return self._make_seq(seqid=seqid)

    def get_seq_array(
        self, *, seqid: str, start: int = None, stop: int = None
    ) -> numpy.ndarray:
        return self._data[seqid][start:stop]

    def get_seq_str(self, *, seqid: str, start: int = None, stop: int = None) -> str:
        return self._alphabet.from_indices(
            self.get_seq_array(seqid=seqid, start=start, stop=stop)
        )

    def get_seq_bytes(
        self, *, seqid: str, start: int = None, stop: int = None
    ) -> bytes:
        return self.get_seq_str(seqid=seqid, start=start, stop=stop).encode("utf8")

    def iter_names(self, *, name_order: tuple[str] = None) -> Iterator:
        yield from process_name_order(self._name_order, name_order)

    def get_seq_view(self, seqid: str) -> SeqDataView:
        seq_len = len(self._data[seqid])
        return SeqDataView(seq=self, seqid=seqid, seq_len=seq_len)

    def iter_seq_view(self, *, name_order: tuple[str] = None) -> Iterator:
        # Should this output SeqView or SeqDataView?
        seqids = process_name_order(self._name_order, name_order)
        for seqid in seqids:
            yield self.get_seq_view(seqid=seqid)


@singledispatch
def seq_to_gap_coords(
    seq: Union[str, numpy.ndarray], moltype: MolType
) -> tuple[str, IndelMap]:
    """
    Takes a sequence with (or without) gaps and returns an ungapped sequence
    and records the position and length of gaps in the original parent sequence
    """
    raise NotImplementedError(f"{seq} not implemented for type {type(seq)}")


@seq_to_gap_coords.register
def _(seq: str, moltype: MolType) -> tuple[str, IndelMap]:
    seq = moltype.make_seq(seq)
    gap_char = moltype.gap
    indel_map, ungapped_seq = seq.parse_out_gaps()

    if indel_map.num_gaps == 0:
        return str(ungapped_seq), numpy.array([], dtype=int)

    return str(ungapped_seq), indel_map


@seq_to_gap_coords.register
def _(seq: numpy.ndarray, moltype: MolType) -> tuple[str, IndelMap]:
    gap_char = moltype.alphabets.degen_gapped.index(moltype.gap)
    # Create boolean array of gaps to get ungapped
    gaps_bool = seq == gap_char
    ungapped = seq[~gaps_bool]

    # no gaps in seq
    if numpy.array_equal(ungapped, seq):
        return ungapped, numpy.array([], dtype=int)

    parent_len = len(seq)
    in_gap = False
    parent_coords = []
    start = 0
    for i, gapped in enumerate(gaps_bool):
        if gapped and not in_gap:
            start = i
            in_gap = True
        if not gapped and in_gap:
            parent_coords.append([start, i])
            in_gap = False
        if gapped and i == parent_len - 1:
            # End of the sequence
            parent_coords.append([start, i + 1])

    # Format for IndelMap
    parent_coords = numpy.array(parent_coords)
    gap_lengths = numpy.array([end - start for start, end in parent_coords])
    cum_lengths = gap_lengths.cumsum()
    # Get gap start positions in sequence coords
    gap_pos = parent_coords.T[0] - numpy.append(0, cum_lengths[:-1, numpy.newaxis])

    indel_map = IndelMap(
        gap_pos=gap_pos, cum_gap_lengths=cum_lengths, parent_length=parent_len
    )

    return ungapped, indel_map


class AlignedDataView(SeqDataView):
    """
    Example
    -------
    data = {"seq1": "ACGT", "seq2": "GTTTGCA"}
    ad = AlignedData.from_strings(data)
    adv = sd.get_aligned_view(seqid="seq1")
    """


@dataclass
class AlignedData:
    # Look out for any overlaps with SeqData
    seqs: Optional[dict[str, numpy.ndarray]] = None
    gaps: Optional[dict[str, numpy.ndarray]] = None
    _moltype: MolType = field(init=False)
    _name_order: tuple[str] = field(init=False)
    _alpha: CharAlphabet = field(init=False)
    align_len: int = 0
    moltype: InitVar[Union[str, None]] = "dna"
    name_order: InitVar[Union[tuple[str], None]] = None

    def __post_init__(self, moltype, name_order):
        self._moltype = get_moltype(moltype)
        self._alpha = self._moltype.alphabets.degen_gapped
        self._name_order = process_name_order(self.seqs, name_order)
        self.seqs = {k: seq_index(v, self._alpha) for k, v in self.seqs.items()}

    @classmethod
    def from_gapped_seqs(
        cls,
        data: dict[str, Union[str, numpy.ndarray]],
        moltype: Union[str, MolType] = "dna",
        name_order: Optional[tuple[str]] = None,
    ):
        """
        Convert dict of {"seq_name": "seq"} to two dicts for seqs and gaps
        """
        seq_lengths = {len(v) for v in data.values()}
        if len(seq_lengths) != 1:
            raise ValueError("All sequence lengths must be the same.")

        align_len = seq_lengths.pop()
        moltype = get_moltype(moltype)

        seqs = {}
        gaps = {}
        for name, seq in data.items():
            seqs[name], gaps[name] = seq_to_gap_coords(seq, moltype)

        name_order = process_name_order(seqs, name_order)

        return cls(
            seqs=seqs,
            gaps=gaps,
            moltype=moltype,
            name_order=name_order,
            align_len=align_len,
        )

    def get_aligned_view(self, seqid: str) -> AlignedDataView:
        # Need to revisit what the variable is called i.e. parent_length
        return AlignedDataView(seq=self, seqid=seqid, seq_len=self.align_len)

    def get_gaps(self, seqid: str) -> numpy.ndarray:
        return self.gaps[seqid]
