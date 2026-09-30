## Fixed

- Close file-like `HTTPError` responses in the central CodeQL identity and Strix
  evidence clients after fail-closed redirects, preventing Python 3.14 resource
  leaks without permitting a second request or weakening bearer-token authority
  checks.
