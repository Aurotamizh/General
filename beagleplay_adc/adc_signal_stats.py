#!/usr/bin/env python3
"""
Sample an external signal on the BeaglePlay ADC and report its statistics.

The BeaglePlay exposes its on-board ADC (TI ADC102S051, 10-bit, 2 channels)
through the Linux IIO subsystem:

    /sys/bus/iio/devices/iio:deviceN/in_voltageX_raw
    /sys/bus/iio/devices/iio:deviceN/in_voltage_scale   (mV per LSB)

This script polls one channel, converts the raw counts to volts and prints:
  * overall mean / standard deviation / min / max / peak-to-peak
  * for a digital (two-level) signal: mean and standard deviation of the
    HIGH level and the LOW level separately, the decision threshold,
    the estimated duty cycle and the number of edges seen
  * the effective sample rate actually achieved

Only the Python standard library is used, so it runs on a stock BeaglePlay
Debian image.

Examples:
    sudo python3 adc_signal_stats.py --list
    sudo python3 adc_signal_stats.py --channel 0 --samples 5000
    sudo python3 adc_signal_stats.py --channel 1 --duration 2 --csv run1.csv
"""

import argparse
import csv
import glob
import os
import statistics
import sys
import time

IIO_ROOT = "/sys/bus/iio/devices"


def read_text(path):
    with open(path) as f:
        return f.read().strip()


def list_devices(iio_root):
    """Return [(device_dir, name, [channel numbers])] for every IIO device."""
    devices = []
    for dev in sorted(glob.glob(os.path.join(iio_root, "iio:device*"))):
        try:
            name = read_text(os.path.join(dev, "name"))
        except OSError:
            name = "?"
        chans = sorted(
            int(os.path.basename(p)[len("in_voltage"):-len("_raw")])
            for p in glob.glob(os.path.join(dev, "in_voltage*_raw"))
            if os.path.basename(p)[len("in_voltage"):-len("_raw")].isdigit()
        )
        devices.append((dev, name, chans))
    return devices


def find_device(iio_root, wanted_name):
    """Pick the IIO device to use: by name if given, else the first ADC found."""
    devices = [d for d in list_devices(iio_root) if d[2]]
    if not devices:
        sys.exit(f"No IIO ADC devices with in_voltage*_raw found under {iio_root}.\n"
                 "Check that the ADC driver is loaded (dmesg | grep -i adc).")
    if wanted_name:
        for dev in devices:
            if wanted_name in (dev[1], os.path.basename(dev[0])):
                return dev
        sys.exit(f"IIO device '{wanted_name}' not found. Use --list to see devices.")
    return devices[0]


def read_scale_mv(dev_dir, channel):
    """mV per LSB, from the per-channel or shared scale attribute."""
    for attr in (f"in_voltage{channel}_scale", "in_voltage_scale"):
        path = os.path.join(dev_dir, attr)
        if os.path.exists(path):
            return float(read_text(path))
    return None


def sample(raw_path, n_samples, duration, interval):
    """Poll the raw sysfs file. Returns (timestamps_s, raw_counts)."""
    times, values = [], []
    # Keep the file open and seek back to 0: much faster than reopening.
    with open(raw_path, "rb", buffering=0) as f:
        t0 = time.perf_counter()
        next_t = t0
        while True:
            now = time.perf_counter()
            if n_samples and len(values) >= n_samples:
                break
            if duration and now - t0 >= duration:
                break
            if interval:
                if now < next_t:
                    time.sleep(next_t - now)
                next_t += interval
            f.seek(0)
            values.append(int(f.read(32)))
            times.append(time.perf_counter() - t0)
    return times, values


def two_level_stats(volts):
    """
    Split samples into LOW and HIGH clusters with a simple iterative
    (k-means, k=2) threshold, which is robust to unequal duty cycles.
    """
    lo, hi = min(volts), max(volts)
    threshold = (lo + hi) / 2
    for _ in range(50):
        low = [v for v in volts if v < threshold]
        high = [v for v in volts if v >= threshold]
        if not low or not high:
            break
        new_t = (statistics.fmean(low) + statistics.fmean(high)) / 2
        if abs(new_t - threshold) < 1e-9:
            break
        threshold = new_t
    low = [v for v in volts if v < threshold]
    high = [v for v in volts if v >= threshold]
    return threshold, low, high


def describe(label, data, unit="V"):
    if not data:
        print(f"  {label:<10} no samples")
        return
    sd = statistics.stdev(data) if len(data) > 1 else 0.0
    print(f"  {label:<10} n={len(data):<7} mean={statistics.fmean(data):.4f} {unit}"
          f"  std={sd:.4f} {unit}  min={min(data):.4f}  max={max(data):.4f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list IIO devices/channels and exit")
    ap.add_argument("--device", help="IIO device name or iio:deviceN (default: first ADC found)")
    ap.add_argument("--channel", type=int, default=0, help="ADC channel number (default 0)")
    ap.add_argument("--samples", type=int, default=0,
                    help="number of samples to take (default 2000 if --duration not set)")
    ap.add_argument("--duration", type=float, default=0, help="sample for this many seconds")
    ap.add_argument("--rate", type=float, default=0,
                    help="target sample rate in Hz (default: as fast as possible)")
    ap.add_argument("--vref", type=float, default=None,
                    help="ADC reference voltage in V; used only if the driver has no scale "
                         "attribute (default 3.3)")
    ap.add_argument("--bits", type=int, default=10, help="ADC resolution, used with --vref (default 10)")
    ap.add_argument("--csv", help="write time_s,raw,volts samples to this CSV file")
    ap.add_argument("--iio-root", default=IIO_ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.list:
        for dev, name, chans in list_devices(args.iio_root):
            print(f"{os.path.basename(dev):<14} name={name:<20} voltage channels={chans}")
        return

    if not args.samples and not args.duration:
        args.samples = 2000

    dev_dir, dev_name, chans = find_device(args.iio_root, args.device)
    if args.channel not in chans:
        sys.exit(f"Channel {args.channel} not available on {dev_name}; channels: {chans}")
    raw_path = os.path.join(dev_dir, f"in_voltage{args.channel}_raw")

    scale_mv = read_scale_mv(dev_dir, args.channel)
    if args.vref is not None or scale_mv is None:
        vref = args.vref if args.vref is not None else 3.3
        scale_mv = vref * 1000.0 / (2 ** args.bits)
        scale_src = f"computed from vref={vref} V, {args.bits} bits"
    else:
        scale_src = "from driver"

    print(f"Device : {os.path.basename(dev_dir)} ({dev_name}), channel {args.channel}")
    print(f"Scale  : {scale_mv:.5f} mV/LSB ({scale_src})")
    print("Sampling...", flush=True)

    interval = 1.0 / args.rate if args.rate else 0
    times, raw = sample(raw_path, args.samples, args.duration, interval)
    if len(raw) < 2:
        sys.exit("Not enough samples collected.")
    volts = [r * scale_mv / 1000.0 for r in raw]

    elapsed = times[-1] - times[0]
    eff_rate = (len(raw) - 1) / elapsed if elapsed > 0 else float("nan")

    print(f"\nCollected {len(raw)} samples in {elapsed:.3f} s "
          f"(effective rate {eff_rate:.0f} Sa/s)\n")

    print("Whole signal:")
    describe("all", volts)
    print(f"  {'raw':<10} mean={statistics.fmean(raw):.2f} LSB  "
          f"std={statistics.stdev(raw):.2f} LSB  p-p={max(volts) - min(volts):.4f} V")

    threshold, low, high = two_level_stats(volts)
    print(f"\nDigital levels (threshold {threshold:.4f} V):")
    describe("HIGH", high)
    describe("LOW", low)
    if high and low:
        edges = sum(1 for a, b in zip(volts, volts[1:]) if (a >= threshold) != (b >= threshold))
        swing = statistics.fmean(high) - statistics.fmean(low)
        print(f"  swing (HIGH-LOW mean) = {swing:.4f} V")
        print(f"  duty cycle (time HIGH) = {100.0 * len(high) / len(volts):.1f} %")
        print(f"  edges seen = {edges}"
              + (f"  -> approx. frequency {edges / 2 / elapsed:.1f} Hz" if elapsed > 0 else ""))
        if edges and eff_rate and edges / 2 / elapsed > eff_rate / 10:
            print("  NOTE: signal frequency is close to the sample rate; duty cycle and "
                  "frequency are unreliable. Level mean/std are still valid.")
    else:
        print("  Only one level seen: the input looks constant (or is a DC level).")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "raw", "volts"])
            w.writerows(zip((f"{t:.6f}" for t in times), raw, (f"{v:.5f}" for v in volts)))
        print(f"\nSamples written to {args.csv}")


if __name__ == "__main__":
    main()
