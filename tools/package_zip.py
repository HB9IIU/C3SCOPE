"""Create a portable/source archive without VCS, bytecode or private env files."""
import argparse
from pathlib import Path
import zipfile


def package_directory(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.is_relative_to(source):
        raise ValueError('The archive must be outside the source directory.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.partial')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, strict_timestamps=False) as archive:
            for path in sorted(source.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symbolic links are not accepted in portable packages.')
                if (not path.is_file() or {'.git', '__pycache__'} & set(path.parts)
                        or path.suffix in ('.pyc', '.pyo') or path.name.startswith('.env')):
                    continue
                compression = zipfile.ZIP_STORED if path.suffix == '.zip' else zipfile.ZIP_DEFLATED
                archive.write(path, path.relative_to(source.parent).as_posix(), compress_type=compression)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    package_directory(args.source, args.destination)
