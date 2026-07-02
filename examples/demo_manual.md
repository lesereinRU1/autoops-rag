# Example Pump Gateway Manual

This synthetic document is created for the AutoOps RAG demo. It does not describe a real product or customer environment.

## Connection

The example gateway listens for Modbus TCP requests on port 1502. The unit identifier is 7. A client should verify the IP address, TCP port, and unit identifier before troubleshooting register data.

## Status codes

`DEMO-100` means that no response arrived before the 3-second monitoring timeout. Check that the gateway is powered, that port 1502 is reachable, and that unit identifier 7 matches the client configuration.

`DEMO-220` means that the requested register offset is outside the implemented range. The example gateway implements holding-register offsets 0 through 31.

## Safe diagnostic sequence

Start with a read-only request for one register at offset 0. Record the request and response before changing configuration. Do not write registers until the operator has confirmed the target device and approved the change.
