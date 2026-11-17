import { Component, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { StationData } from '../../../services/station-data';

@Component({
  imports: [],
  selector: 'app-station',
  styleUrl: './station.css',
  templateUrl: './station.html',
})
export class Station {
  station = signal<any>(null);

  constructor(private stationData: StationData,
              private route: ActivatedRoute) { }

  ngOnInit() {
    this.stationData.getStation(this.route.snapshot.paramMap.get('id'))
      .subscribe(response => this.station.set(response));
  }
}