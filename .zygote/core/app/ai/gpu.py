"""The video cards of THIS computer, read through NVIDIA's management library (nvidia-ml-py): a library call, no program is started.
Other makes of card are not read yet; the panel then says so instead of showing nothing."""
from functional.core import ZygoteError

MIB = 1024 * 1024


def local_gpus():
    """[{'name', 'total_mib', 'used_mib', 'load'}, …]. Raises ZygoteError (with the reason) when the cards cannot be read."""
    try:
        import pynvml
    except ImportError as error:
        raise ZygoteError('nvidia-ml-py is not installed (it comes with the first start of Zygote).') from error
    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError as error:
        raise ZygoteError(f'No NVIDIA driver answered ({error}).') from error
    try:
        cards = []
        for number in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(number)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            load = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu                  # percent of the last moment the GPU was busy
            cards.append({'name': name.decode() if isinstance(name, bytes) else name, 'total_mib': memory.total // MIB, 'used_mib': memory.used // MIB,
                          'load': load})
        return cards
    except pynvml.NVMLError as error:
        raise ZygoteError(f'The video card could not be read ({error}).') from error
    finally:
        pynvml.nvmlShutdown()
