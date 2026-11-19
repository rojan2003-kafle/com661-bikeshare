import { Component, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { StationData } from '../../services/station-data';

@Component({
  imports: [RouterLink],
  selector: 'app-home',
  styleUrl: './home.css',
  templateUrl: './home.html',
})
export class Home {
  totalStations = signal(0);

  constructor(private stationData: StationData) { }

  ngOnInit() {
    this.stationData.getStations(1).subscribe(response => {
      this.totalStations.set(response.total);
    });
  }
}