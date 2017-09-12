from telegram_bot_vm.machine import BotVM

from . import get_redis_connection
from . import constructor
from .operators_server import Operator
from .operators_server import OperatorsDispatcher
from .helpers import StoredObject
from telegram import Bot

running_bots = {}


class BotTemplateNotSelected(Exception):
    pass


class BotRunnerContext(StoredObject):
    MNEMONIC = 'bot_context'

    def init(self, name):
        self.name = name
        self.redis.rpush('bot_contexts_list', self.id)

    def clean_up(self):
        for operator in self.operators:
            operator.delete()
        self.redis.delete('bot_contexts:%d:name' % self.id)
        self.redis.delete('bot_contexts:%d:bot_template' % self.id)
        self.redis.delete('bot_contexts:%d:token' % self.id)
        self.redis.delete('bot_contexts:%d:operators' % self.id)
        self.redis.delete('bot_contexts:%d:visits' % self.id)
        self.redis.lrem('bot_contexts_list', self.id)

    @property
    def running(self):
        return True if self.id in running_bots else False

    @property
    def name(self):
        n = self.redis.get('bot_contexts:%d:name' % self.id)
        if n is not None:
            return n.decode()

    @name.setter
    def name(self, name):
        self.redis.set('bot_contexts:%d:name' % self.id, name)

    @property
    def token(self):
        t = self.redis.get('bot_contexts:%d:token' % self.id)
        if t is not None:
            return t.decode()

    @token.setter
    def token(self, token):
        Bot._validate_token(token)
        self.redis.set('bot_contexts:%d:token' % self.id, token)

    @property
    def bot_template(self):
        bot_template_id = self.redis.get('bot_contexts:%d:bot_template' % self.id)
        if bot_template_id is not None:
            return constructor.BotTemplate(int(bot_template_id))

    @bot_template.setter
    def bot_template(self, bot_template):
        if bot_template is None:
            self.redis.delete('bot_contexts:%d:bot_template' % self.id)
        else:
            self.redis.set('bot_contexts:%d:bot_template' % self.id, bot_template.id)

    def add_operator(self, operator):
        if operator not in self.operators:
            self.redis.rpush('bot_contexts:%d:operators' % self.id, operator.id)
        else:
            raise OperatorAlreadyAdded

    def delete_operator(self, operator):
        self.redis.lrem('bot_contexts:%d:operators' % self.id, operator.id)

    @property
    def operators(self):
        operators = self.redis.lrange('bot_contexts:%d:operators' % self.id, 0, -1)
        return tuple(Operator(int(o)) for o in operators)

    @classmethod
    def list(cls):
        redis_ = get_redis_connection()
        bot_contexts = redis_.lrange('bot_contexts_list', 0, -1)
        return tuple(cls(int(c)) for c in bot_contexts)

    def get_visits_per_day(self, date_):
        visits = self.redis.hget('bot_contexts:%d:visits', date_.isoformat())
        return 0 if visits is None else int(visits)

    def run(self):
        if self.bot_template is not None:
            actions = self.bot_template.compile()
            process = BotVM.run(actions, self.token,
                                add_properties={'operators_dispatcher': OperatorsDispatcher(self.operators),
                                                'bot_context_id': self.id})
            running_bots[self.id] = process
        else:
            raise BotTemplateNotSelected

    def stop(self):
        process = running_bots.get(self.id)
        if process is not None:
            process.terminate()
            del running_bots[self.id]


class OperatorAlreadyAdded(Exception):
    pass


def is_operator_locked(operator):
    for context in BotRunnerContext.list():
        for oper in context.operators:
            if oper == operator:
                return True
    return False


def is_bot_template_locked(bot_template):
    for context in BotRunnerContext.list():
        if context.bot_template == bot_template:
            return True
    return False
