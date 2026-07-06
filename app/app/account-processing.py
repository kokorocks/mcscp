# Source - https://stackoverflow.com/a/23768422
# Posted by Chris Dutrow, modified by community. See post 'Timeline' for change history
# Retrieved 2026-05-24, License - CC BY-SA 4.0

def get_hashed_password(plain_text_password):
    # Hash a password for the first time
    #   (Using bcrypt, the salt is saved into the hash itself)
    return bcrypt.hashpw(plain_text_password, bcrypt.gensalt())

def check_password(plain_text_password, hashed_password):
    # Check hashed password. Using bcrypt, the salt is saved into the hash itself
    return bcrypt.checkpw(plain_text_password, hashed_password)
