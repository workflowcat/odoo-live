"""Об'єкт, що записує, які значення реально прочитало правило.

Формули правил (`amount_python_compute` тощо) виконуються через safe_eval і не кажуть,
які значення вони взяли. Але всі вони дістають payroll.ua через один метод -
BaseBrowsableObject.__getattr__. Стаємо в ці двері й записуємо кожне звертання.
Ніякого розбору формул, ніякого другого розрахунку - лише спостереження за тим самим."""

from odoo.addons.payroll.models.base_browsable import BaseBrowsableObject


class RecordingBrowsable(BaseBrowsableObject):
    """BaseBrowsableObject, який поводиться точно як батько, але кожне читання
    атрибута дописує ім'я ключа у спільну колекцію, передану ззовні (одна на
    листок, не на клас - інакше сліди різних листків в одному циклі змішаються).

    Читання ключа, якого немає у словнику, теж записується: так видно, що
    правило шукало вхід, якого немає, а не лише те, що знайшло."""

    def __init__(self, vals_dict, reads):
        super().__init__(vals_dict)
        # base_fields визначає, які імена йдуть у super().__setattr__ (службові),
        # решта - у self.dict (payroll-значення). "reads" - службове, як і "dict".
        self.__dict__["base_fields"].append("reads")
        self.reads = reads

    def __getattr__(self, attr):
        # Той самий порядок дій, що в батька: читаємо self.dict напряму, не self.reads
        # через getattr (щоб не зациклитись, хоч тут це і не загрожує - reads завжди
        # в __dict__ після __init__).
        present = attr in self.dict
        # Службові імена (__deepcopy__, __iter__ і подібні) питає не формула, а Python.
        # У слід вони не йдуть, інакше кожен крок обростає шумом.
        if not attr.startswith("__"):
            self.reads.append(attr)
        return (present and self.dict[attr]) or 0.0
