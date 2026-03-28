#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <vector>

#include "MinaCalc.h"

int main()
{
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    unsigned keycount = 4;
    float rate = 1.0F;
    float goal = 0.93F;
    int n = 0;

    if (!(std::cin >> keycount >> rate >> goal >> n)) {
        return 2;
    }

    std::vector<NoteInfo> notes;
    notes.reserve(static_cast<size_t>(std::max(0, n)));

    for (int i = 0; i < n; ++i) {
        unsigned notes_mask = 0U;
        float row_time = 0.F;
        if (!(std::cin >> notes_mask >> row_time)) {
            return 3;
        }
        notes.push_back(NoteInfo{ notes_mask, row_time });
    }

    if (notes.size() <= 1) {
        std::cout << "0 0 0 0 0 0 0 0\n";
        return 0;
    }

    Calc calc;
    auto result = MinaSDCalc(notes, rate, goal, keycount, &calc);

    if (result.size() < 8) {
        return 4;
    }

    std::cout << std::fixed << std::setprecision(6)
              << result[Skill_Overall] << " "
              << result[Skill_Stream] << " "
              << result[Skill_Jumpstream] << " "
              << result[Skill_Handstream] << " "
              << result[Skill_Stamina] << " "
              << result[Skill_JackSpeed] << " "
              << result[Skill_Chordjack] << " "
              << result[Skill_Technical] << "\n";

    return 0;
}
