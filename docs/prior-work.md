# Prior work: gesture wands and how SpellWand compares

Researched 2026-10-11. Some details come from search-result summaries rather than the
primary source; those are marked *(summary only)*.

## Existing systems

| System | Sensing | Recognition | How it controls things |
|---|---|---|---|
| Universal Studios interactive wands | **No electronics in the wand.** Retroreflective tip, IR LEDs and an IR camera at each display | Camera tracks the tip in 2D; image processing matches the path against stored gestures | The display itself reacts ([LearnOpenCV][lcv], [patent][pat]) |
| Adam Thole's DIY version | Same IR idea, Raspberry Pi NoIR camera | Matches the traced shape against a database | Sends commands to Home Assistant (lights, music) ([Open Electronics][oe]) |
| Kano Harry Potter Coding Wand | 9-axis IMU (accelerometer, gyroscope, magnetometer) | **Hold a button** to start; screen shows a cursor trail; algorithm not published | BLE to a tablet/PC app; gestures trigger code blocks ([Dezeen][dz], [PCWorld][pcw]) |
| uWave (Rice / Motorola, 2008) | 3-axis accelerometer | **Button held during the gesture**, quantization, **DTW against templates**, template adaptation; works from **one** example per gesture; 98.6 % accuracy reported on the project page (not checked against the paper) | Research prototype ([UIST demo][uw1], [project page][uw2], [Akl & Valaee][akl]) |
| TensorFlow Lite Micro "magic wand" (Arduino Nano 33 BLE Sense) | Accelerometer + gyroscope | Gravity from the accelerometer, **gyro integrated into orientation**, projected into a 2D stroke in a gravity-aligned plane, split by movement, drawn into a 32x32 image, classified by a small CNN (digits 0-9) | Stroke streamed over BLE to a **web page that draws it live** ([README][mw1], [source][mw2]) |
| rbaron/spellcaster | nRF52833 + LSM6DSL IMU | Button to record a spell; compares with stored spells; **always picks the best match**, so the author notes false positives on unseen spells | BTHome BLE adverts to Home Assistant, Zigbee, or BLE-HID key presses ([GitHub][sc]) |
| Nordic "Wireless Wizard Wand" | nRF52840 + MPU6050 | Edge Impulse ML model | Zigbee *(summary only)* ([Nordic blog][nd]) |
| Sam March's wand | Dialog DA14531 | not described | Puts the gesture in **BLE advertisement data** that smart plugs read without pairing *(summary only)* ([Hackster][hs]) |
| Gesture Recognition Toolkit (GRT) DTW | any time series | One template per class (the example closest to the others); **per-class rejection threshold = mean + k x standard deviation** of the template's DTW distances to the other training examples | Library ([source][grt]) |
| Voight-Kampff Machine | any | Picks a rejection threshold from synthetic positive and negative samples; warns that a loose threshold gives false positives on busy, continuous movement | Method ([UCF][vkm]) |

## What this means for SpellWand

1. **Our core approach is well established.** Holding a button, then comparing against a few
   recorded examples with DTW and rejecting poor matches, is the uWave / Kano family. It
   needs very few training examples, which suits a student project better than training a
   neural network.
2. **Rejection really matters.** spellcaster's "always pick the best match" gives false
   positives, which is why our `Gesture Classifier` returns `UNKNOWN`.
   *Possible upgrade:* GRT-style **per-gesture thresholds** (mean + k x std of each gesture's
   own example distances) with a single "strictness" knob k in the UI. A sloppy gesture like
   ZIGZAG would get a looser threshold than a tight one like HORIZONTAL_LINE.
3. **Orientation tracking is the standard trick.** The magic wand estimates gravity, then
   integrates the gyro. SpellWand now does the same in `motion_trace.py`: for the 3D view,
   and in the classifier to subtract gravity at every sample. On simulated data that took
   the safety margin between real gestures and casual movement from about 3x to about 5-6x.
   Classifying the drawn stroke alone was *worse* on our simulated data (random wobbles
   also trace shapes), so we kept raw motion and used the trace for display.
4. **Ways to control devices**, from simplest to most ambitious:
   - the Mac runs a software action (key press, AppleScript, shell command): the current plan;
   - the Mac tells the ESP32 to switch a GPIO (LED or relay) with `EXECUTE_ACTION`;
   - the Mac calls a Home Assistant webhook or publishes over MQTT;
   - stretch goal: the wand broadcasts BTHome BLE adverts straight to Home Assistant, with no Mac.
5. **Live stroke drawing in a browser** (magic wand) matches our planned `SpellWand UI` motion view.

[lcv]: https://learnopencv.com/using-harry-potter-interactive-wand-with-opencv-to-create-magic
[pat]: https://patents.justia.com/patent/20180329511
[oe]: https://www.open-electronics.org/harry-potter-approved-smart-home-assistant/
[dz]: https://www.dezeen.com/2018/09/26/kanos-harry-potter-wand-kit-lets-you-code-spells/amp/
[pcw]: https://www.pcworld.com/article/3292076/consumer-electronics/hands-on-with-the-harry-potter-kano-coding-kit.html
[uw1]: https://uist.acm.org/archive/adjunct/2008/pdf/demos/paper179.pdf
[uw2]: https://yecl.org/project_uwave.html
[akl]: https://www.comm.utoronto.ca/~valaee/Publications/Akl-TST-2011.pdf
[mw1]: https://github.com/tensorflow/tflite-micro-arduino-examples/blob/main/examples/magic_wand/README.md
[mw2]: https://github.com/tensorflow/tflite-micro-arduino-examples/blob/main/examples/magic_wand/magic_wand.ino
[sc]: https://github.com/rbaron/spellcaster/blob/main/README.md
[nd]: https://devzone.nordicsemi.com/nordic/nordic-blog/b/blog/posts/the-wireless-wizard-wand
[hs]: https://www.hackster.io/news/cast-spells-on-devices-with-this-magic-iot-wand-837084c4ff62
[grt]: https://github.com/nickgillian/grt/blob/master/GRT/ClassificationModules/DTW/DTW.cpp
[vkm]: https://www.eecs.ucf.edu/isuelab/research/vkm/
