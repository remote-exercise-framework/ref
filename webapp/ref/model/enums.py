from enum import Enum


class CourseOfStudies(Enum):
    MASTER_ITS_NS = 'Master ITS/Netze und Systeme'
    MASTER_ITS_IS = 'Master ITS/Informationstechnik'
    MASTER_AI = 'Master Angewandte Informatik'
    OTHER = 'Other'

class ExerciseBuildStatus(Enum):
    NOT_BUILD = 'NOT_BUILD'
    BUILDING = 'BUILDING'
    FINISHED = 'FINISHED'
    FAILED = 'FAILED'

class ExerciseServiceType(Enum):
    ENTRY = 'Entry Service'
    PERIPHERAL = 'Peripheral Service'


class UserAuthorizationGroups(Enum):
    ADMIN = 'Admin'
    GRADING_ASSISTANT = 'Grading Assistant'
    STUDENT = 'Student'
