"""LAN viewers may use the receiver protocol, not arbitrary bootloader bytes."""
import re


READ_QUERIES = {'INFO', 'CAPS', 'SPECINFO?', 'TRANSPORT?', 'RANGE?', 'LIMITS?',
                'GAIN?', 'VERSION?', 'GPIO?', 'RELEASE'}
RECEIVER_COMMAND = re.compile(
    r'(?:SYNC [0-9]{1,24}|FREQ [0-9]{1,4}|BANDWIDTH [0-9]{1,3}'
    r'|GAIN (?:HARDWARE|MANUAL [0-9]{1,3})|(?:LPF|ALPF) (?:AUTO|[0-9.]{1,8})'
    r'|BAUD (?:1000000|2000000)|CAP(?:8|16|20) [0-9]{1,8} [0-9]{1,8}'
    r'|SPEC [0-9]{1,8}(?: [0-9]{1,8}){4,7})\Z')


def validate_remote_write(data):
    if (not data or len(data) > 2048 or not data.endswith(b'\n')
            or any(b not in (10, 13) and not 32 <= b <= 126 for b in data)):
        raise ValueError('LAN serial access accepts receiver commands only.')
    for line in data.decode('ascii').splitlines():
        if line and line not in READ_QUERIES and not RECEIVER_COMMAND.fullmatch(line):
            raise ValueError('This serial command is not available to LAN viewers.')
