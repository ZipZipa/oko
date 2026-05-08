from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_for_photo = State()
    waiting_for_name = State()
    waiting_for_birth_date = State()


class PalmStates(StatesGroup):
    waiting_for_palm_left = State()
    waiting_for_palm_right = State()


class PartnerStates(StatesGroup):
    waiting_for_partner_name = State()
    waiting_for_partner_birthdate = State()
    waiting_for_partner_photo = State()