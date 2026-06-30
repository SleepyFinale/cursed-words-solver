using System.Collections.Generic;
using UnityEngine;

public class WordHistoryController : MonoBehaviour
{
	[SerializeField]
	private GameObject _wordHistoryObjectGO;

	[SerializeField]
	private Transform _wordHistoryObjectsParent;

	public void AddEntry(HistoricWord historicWord)
	{
		Object.Instantiate(_wordHistoryObjectGO, _wordHistoryObjectsParent).GetComponent<WordHistoryObject>().Populate(historicWord, neutralScore: false);
	}

	public void AddPuzzleEntry(List<Tile> tiles, List<TileSolutionState> solutionStates)
	{
		Object.Instantiate(_wordHistoryObjectGO, _wordHistoryObjectsParent).GetComponent<WordHistoryObject>().PopulatePuzzle(tiles, solutionStates);
	}
}
