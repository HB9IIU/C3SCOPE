# Security and intended use

C3SCOPE is a local receiver application, not a public web service.

- Default mode listens on loopback only.
- `--lan` deliberately exposes the viewer to your trusted private network.
  It uses HTTP without authentication. A LAN client can take the available
  receiver session and change receiver settings. One viewer controls it at a time.
- Firmware installation, erasing and Quit require a loopback connection and
  a matching local Origin. Flash/erase also require a short-lived, single-use
  confirmation bound to the selected USB identity.
- LAN serial writes are restricted to receiver commands; bootloader packets,
  GPIO actuation and bootloader signal controls are rejected.
- Host header validation rejects arbitrary DNS names. Do not put the app
  behind a proxy that makes remote clients appear to come from loopback.
- Do not forward its port from a router to the Internet.

For a security issue, use GitHub private vulnerability reporting if enabled,
or contact the maintainer, [HB9IIU](https://github.com/HB9IIU). Do not put
credentials or private information into a public issue.
