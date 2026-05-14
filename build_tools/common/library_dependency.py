"""Repository-relative source files supplied by a reusable library."""



class LibraryDependency:
    def __init__(self, files: list[str]) -> None:
        self._rtl_files = list(files)

    def rtl_files(self) -> list[str]:
        """Return the library's ordered source paths relative to the repository root."""
        return self._rtl_files.copy()
