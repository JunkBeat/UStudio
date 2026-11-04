from typing import TYPE_CHECKING, Any, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from ..classes.generated import PackedBitVector


def reshape(data, shape: Optional[Tuple[int, ...]] = None) -> List[Any]:
    if shape is None:
        return data.tolist() if isinstance(data, np.ndarray) else data
    size = int(np.prod(shape))
    if isinstance(data, np.ndarray) and len(shape) in (1, 2) and size and len(data) % size == 0:
        # whole groups only: numpy gives the same nested lists as the slicing below, at C speed
        return data.reshape((-1, *shape)).tolist()
    if isinstance(data, np.ndarray):
        data = data.tolist()
    if len(shape) == 1:
        m = shape[0]
        return [data[i : i + m] for i in range(0, len(data), m)]
    elif len(shape) == 2:
        m, n = shape
        return [[data[i + j : i + j + n] for j in range(0, m * n, n)] for i in range(0, len(data), m * n)]
    else:
        raise ValueError("Invalid shape")


def _unpack_int_array(packed: "PackedBitVector", start: int, count: int) -> np.ndarray:
    """The `count` values of m_BitSize bits from item `start` on, least significant bit first — what the per-bit
    loop this replaces computed one bit run at a time (a 2.2 M-vertex compressed mesh: 7 s -> well under 1 s)."""
    bit_size = packed.m_BitSize
    if count <= 0:
        return np.zeros(0, dtype=np.int64)
    if bit_size == 0:
        return np.zeros(count, dtype=np.int64)
    first_bit = bit_size * start
    needed_bits = bit_size * count
    first_byte, last_byte = first_bit // 8, (first_bit + needed_bits + 7) // 8
    raw = np.frombuffer(bytes(packed.m_Data[first_byte:last_byte]), dtype=np.uint8)
    if len(raw) < last_byte - first_byte:
        raise IndexError("PackedBitVector data is shorter than its items")
    bits = np.unpackbits(raw, bitorder="little")[first_bit % 8 : first_bit % 8 + needed_bits]
    weights = np.left_shift(np.uint64(1), np.arange(bit_size, dtype=np.uint64))
    values = np.zeros(count, dtype=np.uint64)
    step = max(1, (1 << 22) // bit_size)            # bounded memory: ~4 M bits per round
    for lo in range(0, count, step):
        hi = min(count, lo + step)
        chunk = bits[lo * bit_size : hi * bit_size].reshape(hi - lo, bit_size).astype(np.uint64)
        values[lo:hi] = chunk @ weights
    return values.astype(np.int64) if bit_size < 64 else values


def unpack_ints(
    packed: "PackedBitVector",
    start: int = 0,
    count: Optional[int] = None,
    shape: Optional[Tuple[int, ...]] = None,
) -> List[Any]:
    assert packed.m_BitSize is not None
    if count is None:
        count = packed.m_NumItems
    return reshape(_unpack_int_array(packed, start, count), shape)


def unpack_floats(
    packed: "PackedBitVector",
    start: int = 0,
    count: Optional[int] = None,
    shape: Optional[Tuple[int, ...]] = None,
) -> List[Any]:
    assert packed.m_BitSize is not None and packed.m_Range is not None and packed.m_Start is not None

    # avoid zero division of scale
    if packed.m_BitSize == 0:
        quantized = [packed.m_Start] * (packed.m_NumItems if count is None else count)
        return reshape(quantized, shape)
    # read as int and cast up to double to prevent loss of precision (the same double arithmetic as before)
    ints = _unpack_int_array(packed, start, packed.m_NumItems if count is None else count)
    scale = packed.m_Range / ((1 << packed.m_BitSize) - 1)
    return reshape(ints.astype(np.float64) * scale + packed.m_Start, shape)


# def pack_ints(
#     data: npt.NDArray[np.uint], bitsize: Optional[int] = 0
# ) -> PackedBitVector:
#     # ensure that the data type is unsigned
#     assert "uint" in data.dtype.name

#     m_NumItems = data.size

#     maxi = data.max()
#     # Prevent overflow
#     if bitsize:
#         m_BitSize = bitsize
#     else:
#         m_BitSize = (32 if maxi == 0xFFFFFFFF else np.ceil(np.log2(maxi + 1))) % 256
#     m_Data = np.zeros((m_NumItems * m_BitSize + 7) // 8, dtype=np.uint8)

#     indexPos = 0
#     bitPos = 0
#     for x in data:
#         bits = 0
#         while bits < m_BitSize:
#             m_Data[indexPos] |= (x >> bits) << bitPos
#             num = min(m_BitSize - bits, 8 - bitPos)
#             bitPos += num
#             bits += num
#             if bitPos == 8:
#                 indexPos += 1
#                 bitPos = 0

#     return PackedBitVector(m_NumItems=m_NumItems, m_BitSize=m_BitSize, m_Data=m_Data)


# def pack_floats(
#     data: npt.NDArray[np.floating[Any]],
#     bitsize: Optional[int] = None,
# ) -> PackedBitVector:
#     min = data.min()
#     max = data.max()
#     range = max - min
#     data_f64 = data.astype(np.float64)
#     # rebase to 0
#     data_f64 -= min
#     # scale to [0, 1]
#     data_f64 /= range
#     # quantize to [0, 2^bit_size - 1]
#     bitsize = bitsize or max(data.itemsize, 32)
#     assert bitsize is not None

#     data_f64 *= (1 << bitsize) - 1
#     # pack the data
#     packed = pack_ints(data_f64.astype(np.uint32), bitsize)
#     packed.m_Start = min
#     packed.m_Range = range
#     return packed

__all__ = ("unpack_ints", "unpack_floats")
