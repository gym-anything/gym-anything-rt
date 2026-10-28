# Fast Input and Screenshots

In the live setting, any delay between an action and its effect counts against the agent. `--fast-io` therefore sends every action and screenshot over a direct connection between the agent's client and its own sandbox. All results in the paper use this route with the Sandweave backend. Its median time from sending an action to receiving the resulting screenshot was below 50 ms in our timing tests.

## Requirements

- The Sandweave inner runner, with `sandweave[desktop]` 0.2.46 or newer.
- The client and the Sandweave worker on the same machine. The runtime checks the actual connection and refuses a forwarded or relayed one. A matching hostname alone is not accepted as proof of a direct connection.

## Action delivery

The client keeps a persistent connection to an input service inside the sandbox, `shared_scripts/scheduled_input.py`. The service executes each batch of mouse and keyboard actions in order and returns an acknowledgement once the X server has processed the input. Browser event handling and repaint complete later. Scheduled actions wait against the sandbox clock.

An uncertain acknowledgement never triggers a replay of the input. Each request carries an identity. A retried request with the same identity is not executed again, and a different request that reuses an identity is rejected.

## Screenshot delivery

Screenshots are captured natively through Sandweave's `desktop.capture_image(format="jpeg", quality=85, cursor=True)`, or `desktop.capture_png(cursor=True)` when `runner_options.capture_image_format` is `"png"`. Each frame carries its capture start and end times. The image is encoded once at full resolution, and those bytes reach the agent unchanged. The client never resizes or re-encodes it.

A live observation is one frame. A paused observation advances the game through its observation window and captures the configured number of frames, then holds the game paused until the next action.

## Measuring latency

Time a request from just before the HTTP request starts until the complete response body, including the image, has arrived. Loading the image and model inference fall outside this measurement. Profile the same request path the evaluation uses, and keep per-request samples so that the mean, median and 95th percentile can be reported.
