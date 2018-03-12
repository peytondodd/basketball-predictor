import csv
import pandas as pd
import random
from common import (differential_vector,
                    extract_stats_components,
                    read_team_stats_file)
from predictor import Predictor


FIELD = '2018_field.csv'
NUM_SIMS = 100


def update_points(points, matchups, predictions):
    for i in range(len(matchups)):
        home, away = matchups[i]
        try:
            points[home] += predictions[i][0]
        except KeyError:
            points[home] = predictions[i][0]
        try:
            points[away] += predictions[i][1]
        except KeyError:
            points[away] = predictions[i][1]
    return points


def predict_all_matches(predictor, team_stats, teams, matchups, points):
    fields_to_rename = {'win_loss_pct': 'win_pct',
                        'opp_win_loss_pct': 'opp_win_pct'}
    prediction_stats = pd.DataFrame()
    match_stats = []

    for matchup in matchups:
        home, away = matchup
        home_stats = team_stats[home]
        away_stats = team_stats['%s_away' % away]
        match_stats.append(pd.concat([away_stats, home_stats], axis=1))
    prediction_stats = pd.concat(match_stats)
    match_vector = differential_vector(prediction_stats)
    match_vector.rename(columns=fields_to_rename, inplace=True)
    match_stats_simplified = predictor.simplify(match_vector)
    predictions = predictor.predict(match_stats_simplified, int)
    points = update_points(points, matchups, predictions)
    return points


def create_variance(stats_dict, stdev_dict):
    local_stats_dict = {}

    for team, stats in stats_dict.items():
        local_stats = {}
        for stat in stats:
            min_val = -1 * float(stdev_dict[stat])
            max_val = abs(min_val)
            variance = random.uniform(min_val, max_val)
            new_value = float(stats[stat]) + variance
            local_stats[stat] = new_value
        local_stats_dict[team] = pd.DataFrame([local_stats])
    return local_stats_dict


def determine_winner(points, matchups):
    winners = []

    for matchup in matchups:
        home, away = matchup
        print '%s vs %s' % (home, away)
        if points[away] > points[home]:
            winners.append(away)
            print '  %s' % away
        else:
            winners.append(home)
            print '  %s' % home
    return winners


def find_winners(predictor, teams, matchups, team_stats, stdev_dict):
    winners = []
    points = {}

    for iteration in range(NUM_SIMS):
        local_stats_dict = create_variance(team_stats, stdev_dict)
        points = predict_all_matches(predictor, team_stats, teams, matchups,
                                     points)
    winners = determine_winner(points, matchups)
    return winners


# Due to the way the field is imported, the top team will play the bottom team
# in the list every round, with the 2nd team playing the 2nd to last, etc.
def get_matchups(teams):
    matchups = []

    for i in range(0, len(teams) / 2):
        matchups.append([teams[i], teams[-1 - i]])
    return matchups


def load_team_stats(teams):
    stats_dict = {}
    stdev_dict = {}
    combined_stats = pd.DataFrame()

    for team in teams:
        stats = read_team_stats_file('team-stats/%s' % team)
        home_stats = extract_stats_components(stats)
        away_stats = extract_stats_components(stats, away=True)
        stats_dict[team] = home_stats
        stats_dict['%s_away' % team] = away_stats
        combined_stats = combined_stats.append(home_stats)
        combined_stats = combined_stats.append(away_stats)
    for col in combined_stats:
        stdev_dict[col] = combined_stats[col].std()
    return stats_dict, stdev_dict


def import_teams():
    with open(FIELD, 'rb') as field:
        reader = csv.reader(field, delimiter=',')
        for line in reader:
            # The NCAA field is a flat list of teams in order of their seed
            return line


def main():
    rounds = ['Round of 64', 'Round of 32', 'Sweet 16', 'Elite 8', 'Final 4',
              'Championship']
    predictor = Predictor()
    teams = import_teams()
    team_stats, stdev_dict = load_team_stats(teams)
    for r in rounds:
        print '=' * 80
        print ' %s' % r
        print '=' * 80
        matchups = get_matchups(teams)
        teams = find_winners(predictor, teams, matchups, team_stats, stdev_dict)


if __name__ == "__main__":
    main()
