"""How long a username or a presented password may be.

ONE PLACE, because two sides must agree. Account creation refuses a
username longer than MAX_USERNAME_LENGTH, and login treats one as a
failed attempt: if creation allowed what login refused, that account
could never log in.

E-02, MEASURED BEFORE: login accepted a 20,000-character username --
and wrote a login_attempts row keyed by it -- and passed a
200,000-character password to argon2 for hashing. Nothing bounded
either, before authentication, for anyone.
"""

# Usernames: nothing limited them at creation either. 128 is generous
# for a name typed at a login form; this deployment's longest is 9.
MAX_USERNAME_LENGTH = 128

# A PRESENTED password, at login -- deliberately NOT the password
# policy's 256. That policy applies when a password is set, and arrived
# in patch 300; an account whose password predates it may be longer, and
# must still be able to log in. 1,024 keeps every such account, and
# still refuses the 200,000-character hashing cost.
MAX_LOGIN_PASSWORD_LENGTH = 1024
