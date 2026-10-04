# BeaglePlay ADC – external signal mean & deviation

`adc_signal_stats.py` samples an external signal on the BeaglePlay ADC and
reports its mean and standard deviation. For a digital (two-level) signal it
also reports the HIGH and LOW levels separately.

## Wiring

> **The ADC input range is 0 V to its reference (~3.3 V). Do not feed 5 V logic
> or negative voltages directly.** Use a resistor divider (e.g. 10 kΩ / 20 kΩ
> for 5 V → 3.3 V) or a level shifter, and always connect signal **GND to
> BeaglePlay GND**.

The BeaglePlay's on-board ADC (TI ADC102S051, 10-bit, 2 channels) is wired to
the **mikroBUS `AN` pin** and the **Grove connector**. Run `--list` to see which
IIO device and channels your kernel exposes, then use a known DC voltage
(for example, connect the input to 3.3 V, then to GND) to confirm which channel
your pin maps to.

```
signal source  ──[optional divider]──►  mikroBUS AN (or Grove analog pin)
signal GND     ─────────────────────►  GND
```

## Usage (on the BeaglePlay)

```sh
# see available ADC devices / channels
sudo python3 adc_signal_stats.py --list

# 5000 samples from channel 0, as fast as possible
sudo python3 adc_signal_stats.py --channel 0 --samples 5000

# 2 seconds at 1 kHz, and save the raw data for plotting
sudo python3 adc_signal_stats.py --channel 0 --duration 2 --rate 1000 --csv run1.csv
```

Options: `--device <name|iio:deviceN>`, `--vref <V>` and `--bits <n>` (only
needed if the driver does not provide `in_voltage_scale`).

## Example output

```
Collected 4001 samples in 2.000 s (effective rate 2000 Sa/s)

Whole signal:
  all        n=4001    mean=0.9791 V  std=1.4740 V  min=0.0000  max=3.2549
  raw        mean=303.82 LSB  std=457.40 LSB  p-p=3.2549 V

Digital levels (threshold 1.6226 V):
  HIGH       n=1200    mean=3.2308 V  std=0.0065 V  min=3.2098  max=3.2549
  LOW        n=2801    mean=0.0144 V  std=0.0050 V  min=0.0000  max=0.0322
  swing (HIGH-LOW mean) = 3.2164 V
  duty cycle (time HIGH) = 30.0 %
  edges seen = 20  -> approx. frequency 5.0 Hz
```

## How to read the numbers

- **Whole-signal mean / std:** for a square wave, the mean is about
  `V_low + duty × swing` and the std is dominated by the swing. It is **not**
  the noise.
- **HIGH / LOW mean:** the actual logic levels (V_OH / V_OL).
- **HIGH / LOW std:** the noise or jitter on each level. This is usually the
  "deviation" you care about for a digital signal. One LSB is about 3.2 mV.
- **Duty cycle / frequency:** valid only when the signal is much slower than
  the effective sample rate. The script polls sysfs from user space, which
  reaches a few kHz at best and has timing jitter. For a fast signal, the
  level statistics remain valid because the samples land at random points in
  the period, but the duty-cycle and frequency figures do not.
