"""
BEWARE: Changes applied to enums that are used as DB column type
are not automatically picked up by flask_migrate. So, do not change
these values without adding a manual crafted migration script.
"""
from enum import Enum


class CourseOfStudies(Enum):
    BACHELOR_ITS = 'Bachelor ITS'
    MASTER_ITS_NS = 'Master ITS/Netze und Systeme'
    MASTER_ITS_IS = 'Master ITS/Informationstechnik'
    MASTER_AI = 'Master Angewandte Informatik'
    OTHER = 'Other'

class ExerciseBuildStatus(Enum):
    """
    Possible states an exercise can be in.
    """
    NOT_BUILD = 'NOT_BUILD'
    BUILDING = 'BUILDING'
    FINISHED = 'FINISHED'
    FAILED = 'FAILED'

class UserAuthorizationGroups(Enum):
    """
    Groups used for permission checks.
    """
    ADMIN = 'Admin'
    GRADING_ASSISTANT = 'Grading Assistant'
    STUDENT = 'Student'
