from bracket_builder import (find_projected_seeds,
                             load_simulation,
                             simulate_tournament)
from conferences import CONFERENCES
from conference_tournaments import BRACKETS
from predictor import Predictor
from rankings import RANKINGS


# These seeds have a different number of teams due to the play-in games.
# All other seeds have 4 teams.
DIFFERENT_NUM_SEEDS = {11: 6, 16: 6}
REGULAR_NUM_SEEDS = 4


def slot_open(seed, filled_slots):
    num_slots = REGULAR_NUM_SEEDS

    if seed in DIFFERENT_NUM_SEEDS.keys():
        num_slots = DIFFERENT_NUM_SEEDS[seed]
    if filled_slots < num_slots:
        return True
    return False


def get_seeds(field):
    seeds = {}

    seed = 1
    for team in field:
        if seed not in seeds.keys():
            seeds[seed] = [team]
            continue
        if slot_open(seed, len(seeds[seed])):
            seeds[seed].append(team)
        else:
            seed += 1
            seeds[seed] = [team]
    return seeds


def sort_field(field):
    ranked_field = []
    ranks = {}

    for team in field:
        rank = RANKINGS.index(team)
        ranks[team] = rank
    for team, rank in sorted(ranks.iteritems(), key=lambda (k,v): (v,k)):
        ranked_field.append(team)
    return ranked_field


def populate_field(auto_bids):
    field = []
    rankings_index = 0

    while len(field) < 68:
        # First load all of the auto-bid teams into the field.
        if len(auto_bids) > 0:
            field.append(auto_bids.pop())
            continue
        # Next, load the at-large bids into the field based on their ranking.
        # If the next team isn't in the field already, add them and continue.
        if RANKINGS[rankings_index] not in field:
            field.append(RANKINGS[rankings_index])
        # If a team is already in the field, keep increasing the rankings_index
        # until a team that isn't already in the field is found.
        else:
            while True:
                if RANKINGS[rankings_index] in field:
                    rankings_index += 1
                    continue
                field.append(RANKINGS[rankings_index])
                break
        rankings_index += 1
    return field


def get_auto_bids(simulation, predictor):
    auto_bids = []

    # Get all of the automatic bid teams who won their conference tournament.
    # This might not necessarily be the first-placed team in the conference.
    for conference in CONFERENCES:
        seeds = find_projected_seeds(simulation, conference)
        auto_bids.append(simulate_tournament(seeds, BRACKETS[conference],
                                             predictor))
    return auto_bids


def main():
    predictor = Predictor()
    simulation = load_simulation()
    auto_bids = get_auto_bids(simulation, predictor)
    # Field is a list of all teams but it is NOT sorted based on rank
    field = populate_field(auto_bids)
    ranked_field = sort_field(field)
    print ranked_field, len(ranked_field)
    seeds = get_seeds(ranked_field)
    print seeds, len(seeds)


if __name__ == "__main__":
    main()
